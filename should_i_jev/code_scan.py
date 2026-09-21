"""Static code scan: find decision-shaped LLM call sites in a codebase.

Python files are parsed with :mod:`ast`: LLM SDK calls are recognized by their
dotted name (``client.chat.completions.create``, ``litellm.completion``,
``client.messages.create`` …), prompt literals are extracted from
messages/prompt kwargs (string constants, f-string constant parts, and
one-level name resolution of visible assignments), and response-handling hints
(``json.loads`` / enum-membership checks) are read from the enclosing function.

JS/TS files are scanned with patterns (no JS parser in the stdlib) — findings
are marked as coarse. The same heuristic core scores every finding, so a code
site and a log row with the same shape land on the same verdict.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from .heuristics import score_from_signals
from .heuristics import (
    signal_decision_language,
    signal_question_shape,
    signal_short_input,
)
from .models import ScoreDetail
from .parsers import _clip

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".eggs",
    "site-packages", ".zcode", ".zcode-workflow-drafts", ".idea", ".vscode",
}
PY_SUFFIXES = {".py"}
JS_SUFFIXES = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}
MAX_FILE_BYTES = 1_000_000

DEFINITE_API_SUFFIXES = (
    "chat.completions.create",
    "completions.create",
    "messages.create",
    "responses.create",
    "litellm.completion",
    "litellm.acompletion",
    "generate_content",
)
GENERIC_API_TAILS = ("completion", "invoke", "complete", "generate", "predict", "classify")
MODEL_HINT_RE = re.compile(
    r"gpt-|claude|gemini|o[134]-mini|o[134]\b|llama|mistral|qwen|deepseek|grok|jev", re.I
)

PROMPT_KWARGS = {"messages", "prompt", "input", "content", "system", "user"}

_ENUM_HINT_RE = re.compile(
    r"\bin\s*[\(\[\{]|\bin\s+[A-Z_][A-Z0-9_]{2,}\b|==\s*[\"'][\w\- ]{1,20}[\"']"
)
_JSON_HINT_RE = re.compile(r"\bjson\.loads\b|\bJSON\.parse\b")


@dataclass
class CodeFinding:
    path: str                 # relative to the scan root
    line: int
    language: str             # "python" | "js"
    api: str                  # dotted call name or matched pattern
    model: str
    prompt_excerpt: str
    handling: List[str] = field(default_factory=list)
    detail: ScoreDetail = field(default_factory=ScoreDetail)


@dataclass
class CodeScan:
    root: str
    findings: List[CodeFinding] = field(default_factory=list)
    files_scanned: int = 0
    errors: int = 0

    @property
    def decision_shaped(self) -> int:
        return sum(1 for f in self.findings if f.detail.verdict in ("likely", "maybe"))


# --------------------------------------------------------------------------- python (AST)

def _dotted_name(node: ast.AST) -> Optional[str]:
    parts: List[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _const_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _strings_from(node: ast.AST, env: Dict[str, str]) -> str:
    """Best-effort literal text: constants, f-string parts, resolved names, sums."""
    s = _const_str(node)
    if s is not None:
        return s
    if isinstance(node, ast.JoinedStr):
        return "".join(
            _const_str(v) or "" for v in node.values if isinstance(v, ast.Constant)
        )
    if isinstance(node, ast.Name):
        return env.get(node.id, "")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _strings_from(node.left, env)
        right = _strings_from(node.right, env)
        return (left + right) if (left or right) else ""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return "\n".join(x for x in (_strings_from(e, env) for e in node.elts) if x)
    if isinstance(node, ast.Dict):
        out = []
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value in ("content", "text", "role"):
                text = _strings_from(v, env)
                if k.value != "role" and text:
                    out.append(text)
        return "\n".join(out)
    return ""


def _scope_env(body: List[ast.stmt]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for stmt in body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                value = _const_str(stmt.value)
                if value is not None:
                    env[target.id] = value
    return env


class _PyScanner(ast.NodeVisitor):
    def __init__(self, src: str) -> None:
        self.src = src
        self.findings: List[CodeFinding] = []
        self._envs: List[Dict[str, str]] = []
        self._funcs: List[ast.AST] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # also async
        self._enter(node)
    visit_AsyncFunctionDef = visit_FunctionDef

    def _enter(self, node) -> None:
        self._envs.append(_scope_env(node.body))
        self._funcs.append(node)
        self.generic_visit(node)
        self._envs.pop()
        self._funcs.pop()

    def _env(self) -> Dict[str, str]:
        merged: Dict[str, str] = {}
        for e in self._envs:
            merged.update(e)
        return merged

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted_name(node.func)
        env = self._env()
        if name and self._is_llm_call(name, node, env):
            prompt = self._prompt_text(node, env)
            model = ""
            for kw in node.keywords:
                if kw.arg == "model":
                    model = _strings_from(kw.value, env) or ""
                    break
            handling = self._handling_hints()
            self.findings.append(
                _make_finding(
                    line=node.lineno,
                    language="python",
                    api=name,
                    model=model,
                    prompt=prompt,
                    handling=handling,
                )
            )
        self.generic_visit(node)

    def _is_llm_call(self, name: str, node: ast.Call, env: Dict[str, str]) -> bool:
        for suffix in DEFINITE_API_SUFFIXES:
            if name.endswith(suffix):
                return True
        for tail in GENERIC_API_TAILS:
            if name.endswith(tail):
                for kw in node.keywords:
                    if kw.arg == "model":
                        model = _strings_from(kw.value, env) or ""
                        if model and MODEL_HINT_RE.search(model):
                            return True
        return False

    def _prompt_text(self, node: ast.Call, env: Dict[str, str]) -> str:
        parts: List[str] = []
        for kw in node.keywords:
            if kw.arg in PROMPT_KWARGS:
                text = _strings_from(kw.value, env)
                if text:
                    parts.append(text)
        for arg in node.args[:1]:  # some SDKs pass messages positionally
            text = _strings_from(arg, env)
            if text:
                parts.append(text)
        return _clip("\n".join(parts), 240, 80, 320)

    def _handling_hints(self) -> List[str]:
        if self._funcs:
            segment = ast.get_source_segment(self.src, self._funcs[-1]) or ""
        else:
            segment = self.src
        return _hints_from_source(segment)


def _hints_from_source(src: str) -> List[str]:
    hints: List[str] = []
    if _JSON_HINT_RE.search(src):
        hints.append("json parse")
    if _ENUM_HINT_RE.search(src):
        hints.append("enum membership")
    if ".choices[0]" in src or ".message.content" in src or ".content[0]" in src:
        hints.append("reads completion text")
    return hints


def _make_finding(
    line: int, language: str, api: str, model: str, prompt: str, handling: List[str]
) -> CodeFinding:
    if "json parse" in handling:
        short_out, structured = 0.7, 1.0
    elif "enum membership" in handling:
        short_out, structured = 0.9, 0.8
    else:
        short_out, structured = 0.0, 0.0
    signals = {
        "short_output": short_out,
        "structured_output": structured,
        "decision_language": signal_decision_language(prompt),
        "question_shape": signal_question_shape(prompt),
        "short_input": signal_short_input(prompt),
        "low_output_diversity": 0.0,
    }
    detail = score_from_signals(signals, prompt)
    return CodeFinding(
        path="",
        line=line,
        language=language,
        api=api,
        model=model,
        prompt_excerpt=prompt,
        handling=handling,
        detail=detail,
    )


def _scan_python(src: str) -> List[CodeFinding]:
    tree = ast.parse(src)
    scanner = _PyScanner(src)
    scanner._envs.append(_scope_env(tree.body))
    scanner.visit(tree)
    return scanner.findings


# --------------------------------------------------------------------------- js/ts (patterns)

# single alternation, longest-first: the same call position must only match once
_JS_API_RE = re.compile(
    r"chat\.completions\.create|litellm\.completion|completions\.create|"
    r"messages\.create|responses\.create"
)
_JS_MODEL_RE = re.compile(r"model\s*:\s*[\"'`]([^\"'`]+)[\"'`]")
_JS_CONTENT_RE = re.compile(r"(?:content|prompt|system)\s*:\s*[\"'`]([^\"'`\n]{12,})[\"'`]")
_JS_STRING_RE = re.compile(r"[\"'`]([^\"'`\n]{16,})[\"'`]")


def _scan_js(src: str) -> List[CodeFinding]:
    findings: List[CodeFinding] = []
    for m in _JS_API_RE.finditer(src):
        pos = m.start()
        # everything we need (model, messages, response handling) follows the call
        window = src[pos: pos + 1600]
        model_match = _JS_MODEL_RE.search(window)
        model = model_match.group(1) if model_match else ""
        prompt_chunks = [c for c in _JS_CONTENT_RE.findall(window)]
        if not prompt_chunks:
            prompt_chunks = _JS_STRING_RE.findall(window)[:2]
        prompt = _clip("\n".join(prompt_chunks), 240, 80, 320)
        if not model and not prompt:
            continue
        handling: List[str] = []
        if _JSON_HINT_RE.search(window):
            handling.append("json parse")
        if _ENUM_HINT_RE.search(window) or ".includes(" in window:
            handling.append("enum membership")
        if ".choices[0]" in window or ".message.content" in window:
            handling.append("reads completion text")
        findings.append(
            _make_finding(
                line=src.count("\n", 0, pos) + 1,
                language="js",
                api=f"{m.group(0)} (pattern)",
                model=model,
                prompt=prompt,
                handling=handling,
            )
        )
    return findings


# --------------------------------------------------------------------------- driver

def scan_code(root: Union[str, Path]) -> CodeScan:
    root = Path(root)
    scan = CodeScan(root=str(root))

    if root.is_file():
        files = [root]
        base = root.parent
    else:
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                files.append(Path(dirpath) / fn)
        base = root

    for path in sorted(files):
        suffix = path.suffix.lower()
        if suffix not in PY_SUFFIXES and suffix not in JS_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            scan.errors += 1
            continue
        scan.files_scanned += 1
        try:
            if suffix in PY_SUFFIXES:
                findings = _scan_python(src)
            else:
                findings = _scan_js(src)
        except SyntaxError:
            scan.errors += 1
            continue
        for f in findings:
            try:
                f.path = str(path.relative_to(base))
            except ValueError:
                f.path = path.name
            scan.findings.append(f)

    scan.findings.sort(key=lambda f: (-f.detail.score, f.path, f.line))
    return scan
