"""Price table and savings math.

Costs come from three places, in priority order:

1. per-call logged cost straight from the log (LiteLLM ``response_cost``,
   Langfuse ``totalCost``, billing CSV ``cost`` columns);
2. a user-supplied ``--price-file`` JSON;
3. the bundled table below — public list prices, with an explicit as-of date.

Savings are modeled as *cost-divisor scenarios*, not absolute JEV prices:
TypeSafe's launch claims JEV is ~400x cheaper and ~200x faster than LLMs on
classification. We deliberately default to a conservative ÷100 for the headline
number and show the vendor claim separately.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Dict, Optional, Tuple

from .models import LlmCall

AS_OF = "2026-09"
PRICE_SOURCE = "public list prices from OpenAI / Anthropic pricing pages"

# USD per 1M tokens: {model: (input, output)}. Edit via --price-file, don't trust blindly.
PRICE_TABLE: Dict[str, Tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-opus-4": (15.00, 75.00),
}

DEFAULT_DIVISOR = 100          # conservative
VENDOR_CLAIM_DIVISOR = 400     # TypeSafe launch claim

_DATE_SUFFIX_RE = re.compile(r"(-\d{4}-\d{2}-\d{2}|-\d{8})$")


def normalize_model(name: str) -> str:
    name = (name or "").strip().lower()
    if "/" in name:                       # litellm style: "openai/gpt-4o-mini"
        name = name.rsplit("/", 1)[-1]
    name = _DATE_SUFFIX_RE.sub("", name)  # "gpt-4o-2024-08-06" -> "gpt-4o"
    return name.strip()


def _fallback_rates() -> Tuple[float, float]:
    ins = [p[0] for p in PRICE_TABLE.values()]
    outs = [p[1] for p in PRICE_TABLE.values()]
    return statistics.median(ins), statistics.median(outs)


def lookup_price(
    model: str, overrides: Optional[Dict[str, Tuple[float, float]]] = None
) -> Tuple[float, float, str, bool]:
    """Return (input_rate, output_rate, matched_key, is_fallback)."""
    norm = normalize_model(model)
    tables: Tuple[Dict[str, Tuple[float, float]], ...] = (
        {normalize_model(k): v for k, v in (overrides or {}).items()},
        PRICE_TABLE,
    )
    for table in tables:
        if norm in table:
            return table[norm][0], table[norm][1], norm, False
    for table in tables:
        for key in sorted(table, key=len, reverse=True):
            if norm.startswith(key):
                return table[key][0], table[key][1], key, False
    fin, fout = _fallback_rates()
    return fin, fout, "(table median)", True


def load_price_file(path: str | Path) -> Dict[str, Tuple[float, float]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("models"), dict):
        data = data["models"]
    if not isinstance(data, dict):
        raise ValueError("price file must be a JSON object of {model: [input, output]}")
    out: Dict[str, Tuple[float, float]] = {}
    for model, rates in data.items():
        if not isinstance(rates, (list, tuple)) or len(rates) != 2:
            raise ValueError(f"price file entry {model!r} must be [input, output] per 1M tokens")
        out[str(model)] = (float(rates[0]), float(rates[1]))
    return out


def estimate_cost(
    call: LlmCall, overrides: Optional[Dict[str, Tuple[float, float]]] = None
) -> Tuple[float, str, bool, bool]:
    """Return (usd, price_key_used, price_is_fallback, tokens_were_approximated).

    Logged costs are taken as the row's total (usage exports already aggregate);
    estimated costs multiply per-request tokens by the row's request_count.
    """
    if call.logged_cost_usd is not None:
        return call.logged_cost_usd, "(logged)", False, False

    in_tok, out_tok = call.input_tokens, call.output_tokens
    approximated = False
    if in_tok is None and call.prompt_excerpt:
        in_tok = len(call.prompt_excerpt) // 4
        approximated = True
    if out_tok is None and call.output_excerpt:
        out_tok = len(call.output_excerpt) // 4
        approximated = True

    fin, fout, key, fallback = lookup_price(call.model, overrides)
    usd = ((in_tok or 0) / 1e6) * fin + ((out_tok or 0) / 1e6) * fout
    return usd * max(1, call.weight), key, fallback, approximated


def savings(migratable_usd: float, divisor: int) -> float:
    return migratable_usd * (1.0 - 1.0 / divisor)
