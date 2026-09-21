"""Decision-shape heuristics: score how "JEV-shaped" an LLM call looks.

JEV (per its launch claims) is for typed decision work: state in, a typed
question (Choice / Score / Noul) out, with probabilities. So the signals below
look for exactly that shape in existing LLM traffic:

===========================  =======================================================
signal                       meaning
===========================  =======================================================
short_output                 completion is a few tokens / one line
structured_output            output is JSON, a number, yes/no, or an enum-like label
decision_language            prompt uses classify / route / rate / judge / extract …
question_shape               prompt reads like a question (ends in '?', is/should/…)
short_input                  prompt is short — decision prompts usually are
low_output_diversity         the same output repeats across calls of this model
===========================  =======================================================

Weights sum to 1.0. A generative-language penalty (write / summarize / draft …
with no decision verbs at all) scales the score down by 40%.

The signal functions take plain text/tokens so both log calls (score_call) and
static code findings (should_i_jev.code_scan) can reuse the same core.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from .models import LlmCall, ScoreDetail

LIKELY_THRESHOLD = 0.60
MAYBE_THRESHOLD = 0.35

WEIGHTS: Dict[str, float] = {
    "short_output": 0.25,
    "structured_output": 0.25,
    "decision_language": 0.20,
    "question_shape": 0.10,
    "short_input": 0.10,
    "low_output_diversity": 0.10,
}

SIGNAL_DOCS: Dict[str, str] = {
    "short_output": "completion is a few tokens / one line",
    "structured_output": "output is JSON, a number, yes/no, or an enum-like label",
    "decision_language": "prompt uses classify / route / rate / judge / extract …",
    "question_shape": "prompt reads like a question",
    "short_input": "prompt is short — decision prompts usually are",
    "low_output_diversity": "same output repeats across calls of this model",
}

_DECISION_RE = re.compile(
    "|".join(
        [
            r"classif", r"categor", r"\brout(?:e|es|ed|ing|er)\b", r"\bjudg(?:e|es|ed|ing)\b",
            r"evaluat", r"\brat(?:e|es|ed|ing)\b", r"\bscor(?:e|es|ed|ing)\b",
            r"\blabel(?:s|ed|ling)?\b", r"\btag(?:s|ged|ging)?\b", r"\bextract",
            r"\bfilter", r"moderat", r"\bverif", r"\bvalidat", r"\bcheck(?:s|ed|ing)?\b",
            r"sentiment", r"\bspam\b", r"toxic", r"\bintent\b", r"\btopic\b", r"triage",
            r"prioriti", r"approv", r"\bflag(?:s|ged|ging)?\b", r"\brank(?:s|ed|ing)?\b",
            r"duplicate", r"\bgrade\b|\bgrading\b", r"\bdecide|\bdecision", r"yes or no",
        ]
    ),
    re.IGNORECASE,
)

_GENERATIVE_RE = re.compile(
    "|".join(
        [
            r"\bwrite|\bwrote|\bwriting\b", r"\bdraft", r"\bsummar", r"\bessay", r"\bstory\b",
            r"\bpoem", r"\brewrite", r"\btranslat", r"\bexplain", r"\bgenerat",
            r"\bbrainstorm", r"\bblog\b", r"\barticle", r"\bcompose", r"\brefactor",
        ]
    ),
    re.IGNORECASE,
)

_BOOL_WORDS = {"yes", "no", "true", "false"}
_ENUM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-/ ]{0,47}")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_QUESTION_START_RE = re.compile(
    r"^\s*(is|are|was|were|does|do|did|should|would|can|could|will|has|have)\b", re.IGNORECASE
)


def _norm_output(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


# --------------------------------------------------------------------------- signals

def signal_short_output(output_tokens: Optional[int] = None, output_text: str = "") -> float:
    if output_tokens is not None:
        t = output_tokens
        if t <= 4:
            return 1.0
        if t <= 16:
            return 0.9
        if t <= 32:
            return 0.6
        if t <= 64:
            return 0.3
        if t <= 128:
            return 0.1
        return 0.0
    n = len((output_text or "").strip())
    if n == 0:
        return 0.0
    if n <= 8:
        return 1.0
    if n <= 32:
        return 0.8
    if n <= 64:
        return 0.5
    if n <= 128:
        return 0.25
    return 0.0


def signal_structured_output(output_text: str) -> float:
    t = (output_text or "").strip()
    if not t:
        return 0.0
    if t[:1] in "{[":
        try:
            json.loads(t)
            return 1.0
        except json.JSONDecodeError:
            return 0.5
    if t.lower() in _BOOL_WORDS:
        return 1.0
    if _NUMBER_RE.fullmatch(t):
        return 1.0
    if len(t) <= 48 and _ENUM_RE.fullmatch(t) and len(t.split()) <= 4:
        return 0.8
    return 0.0


def _language_hits(text: str, regex: re.Pattern) -> int:
    return len(regex.findall(text or ""))


def signal_decision_language(prompt_text: str) -> float:
    hits = _language_hits(prompt_text, _DECISION_RE)
    if hits == 0:
        return 0.0
    return min(1.0, 0.5 + 0.15 * hits)


def signal_question_shape(prompt_text: str) -> float:
    prompt = (prompt_text or "").strip()
    if not prompt:
        return 0.0
    value = 0.0
    if prompt.rstrip().endswith("?"):
        value += 0.7
    if _QUESTION_START_RE.match(prompt):
        value += 0.3
    return min(1.0, value)


def signal_short_input(prompt_text: str, input_tokens: Optional[int] = None) -> float:
    if input_tokens is not None:
        t = input_tokens
        if t <= 512:
            return 1.0
        if t <= 1024:
            return 0.7
        if t <= 2048:
            return 0.4
        if t <= 4096:
            return 0.15
        return 0.0
    n = len((prompt_text or "").strip())
    if n == 0:
        return 0.0
    if n <= 2048:
        return 1.0
    if n <= 4096:
        return 0.7
    if n <= 8192:
        return 0.4
    if n <= 16384:
        return 0.15
    return 0.0


def language_penalty(prompt_text: str) -> float:
    """1.0 normally; 0.6 when the prompt is generative with zero decision verbs."""
    gen = _language_hits(prompt_text, _GENERATIVE_RE)
    dec = _language_hits(prompt_text, _DECISION_RE)
    if gen > 0 and dec == 0:
        return 0.6
    return 1.0


# --------------------------------------------------------------------------- corpus stats

def corpus_stats(calls: List[LlmCall]) -> Dict[str, Dict]:
    """Per-model output-cluster counters, used for the diversity signal."""
    per_model: Dict[str, Counter] = defaultdict(Counter)
    for c in calls:
        key = _norm_output(c.output_excerpt)
        if key:
            per_model[c.model][key] += max(1, c.weight)

    stats: Dict[str, Dict] = {}
    for model, clusters in per_model.items():
        total = sum(clusters.values())
        duplicated = sum(n for n in clusters.values() if n > 1)
        stats[model] = {
            "clusters": clusters,
            "total_outputs": total,
            "dup_rate": (duplicated / total) if total else 0.0,
        }
    return stats


# --------------------------------------------------------------------------- scoring

def score_from_signals(
    signals: Dict[str, float],
    prompt_text: str = "",
    likely_threshold: float = LIKELY_THRESHOLD,
    maybe_threshold: float = MAYBE_THRESHOLD,
) -> ScoreDetail:
    score = sum(WEIGHTS.get(name, 0.0) * value for name, value in signals.items())
    score *= language_penalty(prompt_text)
    score = round(score, 4)
    if score >= likely_threshold:
        verdict = "likely"
    elif score >= maybe_threshold:
        verdict = "maybe"
    else:
        verdict = "unlikely"
    return ScoreDetail(signals=signals, score=score, verdict=verdict)


def score_call(call: LlmCall, stats: Dict[str, Dict]) -> ScoreDetail:
    key = _norm_output(call.output_excerpt)
    cluster_size = 0
    if key:
        cluster_size = stats.get(call.model, {}).get("clusters", {}).get(key, 0)

    if cluster_size >= 5:
        diversity = 1.0
    elif cluster_size >= 2:
        diversity = 0.6
    else:
        diversity = 0.0

    signals = {
        "short_output": signal_short_output(call.output_tokens, call.output_excerpt),
        "structured_output": signal_structured_output(call.output_excerpt),
        "decision_language": signal_decision_language(call.prompt_excerpt),
        "question_shape": signal_question_shape(call.prompt_excerpt),
        "short_input": signal_short_input(call.prompt_excerpt, call.input_tokens),
        "low_output_diversity": diversity,
    }

    detail = score_from_signals(signals, call.prompt_excerpt)
    if not call.prompt_excerpt and not call.output_excerpt:
        # text-less usage-export rows: token shape alone can't justify a verdict
        detail.verdict = "insufficient"
    return detail


def score_corpus(calls: List[LlmCall]) -> List[ScoreDetail]:
    stats = corpus_stats(calls)
    return [score_call(c, stats) for c in calls]
