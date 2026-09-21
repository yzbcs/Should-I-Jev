"""Core data types shared across should-i-jev."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LlmCall:
    """One normalized LLM request (or one aggregated row from a usage export)."""

    call_id: str
    source: str                       # e.g. "litellm_logs.jsonl#L3"
    format: str                       # litellm | langfuse | generic
    model: str = "unknown"
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt_excerpt: str = ""
    output_excerpt: str = ""
    logged_cost_usd: float | None = None
    timestamp: str | None = None
    weight: int = 1                   # aggregated usage rows may stand for N requests


@dataclass
class ScoreDetail:
    """Heuristic decision-shape score for one call."""

    signals: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    verdict: str = "unlikely"         # likely | maybe | unlikely
