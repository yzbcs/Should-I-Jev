"""Parsers for common LLM usage-log / export formats.

Three shapes are recognized:

* ``litellm``  — LiteLLM proxy request logs (messages / response / usage / response_cost)
* ``langfuse`` — Langfuse generation exports (input / output / usage / totalCost)
* ``generic``  — anything with model + token-count columns: OpenAI & Anthropic
  usage exports, billing CSVs, home-rolled JSONL logs. Field aliases cover the
  common spellings; text fields (prompt/output) are optional and unlock the
  richer heuristics when present.

Everything runs locally; nothing leaves the machine.
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .models import LlmCall

log = logging.getLogger("should_i_jev")

SUPPORTED_SUFFIXES = {".jsonl", ".ndjson", ".json", ".csv", ".tsv"}

FORMATS = ("auto", "litellm", "langfuse", "generic")


# --------------------------------------------------------------------------- helpers

def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _int(x: Any) -> Optional[int]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _float(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _text_from_content(content: Any) -> str:
    """Content may be a plain string or a list of typed parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: List[str] = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                t = part.get("text") or part.get("content")
                if isinstance(t, str):
                    parts.append(t)
    return "\n".join(p for p in parts if p)


def _messages_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    out: List[str] = []
    for m in messages:
        if isinstance(m, dict):
            out.append(_text_from_content(m.get("content")))
        elif isinstance(m, str):
            out.append(m)
    return "\n".join(x for x in out if x)


def _clip(text: str, head: int = 300, tail: int = 120, limit: int = 440) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:head] + " … " + text[-tail:]


# --------------------------------------------------------------------------- per-format normalizers

def _normalize_litellm(rec: dict, call_id: str, source: str) -> LlmCall:
    usage = rec.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    response = rec.get("response")
    if isinstance(response, dict):
        try:
            response = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            response = None
    return LlmCall(
        call_id=call_id,
        source=source,
        format="litellm",
        model=str(_first(rec, "model", "model_name") or "unknown"),
        input_tokens=_int(_first(usage, "prompt_tokens", "input_tokens")),
        output_tokens=_int(_first(usage, "completion_tokens", "output_tokens")),
        prompt_excerpt=_clip(_messages_text(rec.get("messages"))),
        output_excerpt=_clip(_text_from_content(response), limit=200),
        logged_cost_usd=_float(_first(rec, "response_cost", "cost", "cost_usd")),
        timestamp=_str_or_none(_first(rec, "timestamp", "created_at", "ts", "call_type_ts")),
    )


def _normalize_langfuse(rec: dict, call_id: str, source: str) -> LlmCall:
    usage = rec.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    body = rec.get("body") or {}
    if not isinstance(body, dict):
        body = {}
    prompt = _text_from_content(rec.get("input")) or _messages_text(body.get("messages"))
    return LlmCall(
        call_id=call_id,
        source=source,
        format="langfuse",
        model=str(_first(rec, "model", "model_name") or "unknown"),
        input_tokens=_int(_first(usage, "input", "prompt_tokens", "input_tokens")),
        output_tokens=_int(_first(usage, "output", "completion_tokens", "output_tokens")),
        prompt_excerpt=_clip(prompt),
        output_excerpt=_clip(_text_from_content(rec.get("output")), limit=200),
        logged_cost_usd=_float(
            _first(rec, "totalCost", "calculatedTotalCost", "cost", "cost_usd")
        ),
        timestamp=_str_or_none(_first(rec, "timestamp", "startTime", "created_at")),
    )


_TOKEN_IN_KEYS = ("input_tokens", "prompt_tokens", "input_token_count", "prompt_token_count")
_TOKEN_OUT_KEYS = ("output_tokens", "completion_tokens", "output_token_count", "completion_token_count")
_USAGE_IN_KEYS = ("input_tokens", "prompt_tokens", "input", "prompt")
_USAGE_OUT_KEYS = ("output_tokens", "completion_tokens", "output", "completion")
_COST_KEYS = ("cost", "cost_usd", "total_cost", "response_cost", "amount", "spend_usd", "totalCost")
_PROMPT_KEYS = ("prompt", "input_text", "question", "user_message", "input")
_OUTPUT_KEYS = ("output", "completion", "response", "output_text", "answer")
_COUNT_KEYS = ("request_count", "n_requests", "requests", "row_count", "n")
_TS_KEYS = ("timestamp", "created_at", "ts", "date", "day", "time")


def _normalize_generic(rec: dict, call_id: str, source: str) -> LlmCall:
    usage = rec.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    in_tok = _int(_first(rec, *_TOKEN_IN_KEYS))
    if in_tok is None:
        in_tok = _int(_first(usage, *_USAGE_IN_KEYS))
    out_tok = _int(_first(rec, *_TOKEN_OUT_KEYS))
    if out_tok is None:
        out_tok = _int(_first(usage, *_USAGE_OUT_KEYS))

    prompt = _first(rec, *_PROMPT_KEYS)
    prompt_text = _messages_text(prompt) if isinstance(prompt, list) else (
        prompt if isinstance(prompt, str) else ""
    )
    output = _first(rec, *_OUTPUT_KEYS)
    if isinstance(output, dict):
        try:
            output = output["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            output = None
    output_text = _messages_text(output) if isinstance(output, list) else (
        output if isinstance(output, str) else ""
    )

    weight = _int(_first(rec, *_COUNT_KEYS)) or 1

    return LlmCall(
        call_id=call_id,
        source=source,
        format="generic",
        model=str(_first(rec, "model", "model_name", "model_slug", "name") or "unknown"),
        input_tokens=in_tok,
        output_tokens=out_tok,
        prompt_excerpt=_clip(prompt_text),
        output_excerpt=_clip(output_text, limit=200),
        logged_cost_usd=_float(_first(rec, *_COST_KEYS)),
        timestamp=_str_or_none(_first(rec, *_TS_KEYS)),
        weight=weight,
    )


def _str_or_none(x: Any) -> Optional[str]:
    return x if isinstance(x, str) else None


_NORMALIZERS: Dict[str, Callable[[dict, str, str], LlmCall]] = {
    "litellm": _normalize_litellm,
    "langfuse": _normalize_langfuse,
    "generic": _normalize_generic,
}


# --------------------------------------------------------------------------- readers

def _read_json_records(path: Path) -> Tuple[List[dict], int]:
    """Return (records, skipped_line_count). Handles JSON arrays and JSONL."""
    text = path.read_text(encoding="utf-8-sig")
    stripped = text.lstrip()
    if stripped.startswith("[") or (stripped.startswith("{") and "\n" not in stripped.rstrip("\n")):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)], 0
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return [r for r in data["data"] if isinstance(r, dict)], 0
        if isinstance(data, dict):
            return [data], 0

    records: List[dict] = []
    skipped = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            log.debug("%s:%d is not valid JSON — skipped", path.name, line_no)
            continue
        if isinstance(rec, dict):
            records.append(rec)
        elif isinstance(rec, list):
            records.extend(r for r in rec if isinstance(r, dict))
    return records, skipped


def _read_csv_records(path: Path) -> List[dict]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        rows = []
        for row in reader:
            rows.append({(k or "").strip().lower(): v for k, v in row.items() if k is not None})
        return rows


def sniff_format(records: Iterable[dict]) -> str:
    for rec in records:
        keys = {str(k).lower() for k in rec.keys()}
        if "messages" in keys or "response_cost" in keys:
            return "litellm"
        if str(rec.get("type", "")).lower() == "generation":
            return "langfuse"
        if "totalcost" in keys or "calculatedtotalcost" in keys:
            return "langfuse"
        usage = rec.get("usage")
        if isinstance(usage, dict):
            ukeys = {str(k).lower() for k in usage.keys()}
            if {"prompt_tokens", "completion_tokens"} & ukeys and "input" not in ukeys:
                return "litellm"
            if {"input", "output"} <= ukeys and "prompt_tokens" not in ukeys:
                return "langfuse"
        return "generic"
    return "generic"


def parse_file(path: str | Path, fmt: str = "auto") -> Tuple[List[LlmCall], int]:
    """Parse one log file into LlmCalls. Returns (calls, skipped_line_count)."""
    p = Path(path)
    if p.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"{p.name}: unsupported extension {p.suffix!r} "
            f"(supported: {', '.join(sorted(SUPPORTED_SUFFIXES))})"
        )
    if not p.is_file():
        raise FileNotFoundError(str(p))

    if p.suffix.lower() in {".csv", ".tsv"}:
        records = _read_csv_records(p)
        effective = "generic"
        skipped = 0
    else:
        records, skipped = _read_json_records(p)
        effective = fmt if fmt != "auto" else sniff_format(records)

    normalizer = _NORMALIZERS[effective]
    calls: List[LlmCall] = []
    for i, rec in enumerate(records):
        call_id = str(_first(rec, "id", "request_id", "row_id") or f"{p.name}#L{i + 1}")
        calls.append(normalizer(rec, call_id, f"{p.name}#L{i + 1}"))
    return calls, skipped
