"""Orchestration: parse files, score calls, attach costs, aggregate results."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .heuristics import (
    LIKELY_THRESHOLD,
    MAYBE_THRESHOLD,
    WEIGHTS,
    corpus_stats,
    score_call,
)
from .maps import MapItem, build_maps
from .models import LlmCall, ScoreDetail
from .parsers import parse_file
from .pricing import (
    AS_OF,
    DEFAULT_DIVISOR,
    PRICE_SOURCE,
    VENDOR_CLAIM_DIVISOR,
    estimate_cost,
    load_price_file,
)
from .pricing import savings as _savings

Pair = Tuple[LlmCall, ScoreDetail]

VERDICT_ORDER = ("likely", "maybe", "unlikely", "insufficient")
VERDICT_LABELS = {
    "likely": "likely JEV-shaped",
    "maybe": "worth a look",
    "unlikely": "keep on LLM",
    "insufficient": "insufficient data",
}

class Audit:
    def __init__(
        self,
        files: List[str],
        pairs: List[Pair],
        skipped_lines: int,
        divisor: int = DEFAULT_DIVISOR,
        divisor_optimistic: int = VENDOR_CLAIM_DIVISOR,
        price_as_of: str = AS_OF,
        price_source: str = PRICE_SOURCE,
    ) -> None:
        self.files = files
        self.pairs = pairs
        self.skipped_lines = skipped_lines
        self.divisor = divisor
        self.divisor_optimistic = divisor_optimistic
        self.price_as_of = price_as_of
        self.price_source = price_source
        self.generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self._costs: Dict[int, Tuple[float, str, bool, bool]] = {}

    # ------------------------------------------------------------------ basics

    @property
    def total_calls(self) -> int:
        return sum(max(1, c.weight) for c, _ in self.pairs)

    @property
    def models(self) -> List[str]:
        return sorted({c.model for c, _ in self.pairs})

    def cost_of(self, call: LlmCall) -> Tuple[float, str, bool, bool]:
        key = id(call)
        if key not in self._costs:
            self._costs[key] = estimate_cost(call, self.price_overrides)
        return self._costs[key]

    price_overrides: Optional[Dict] = None  # set by run_audit

    # ------------------------------------------------------------------ aggregates

    def counts(self) -> Dict[str, int]:
        out = {v: 0 for v in VERDICT_ORDER}
        for call, detail in self.pairs:
            out[detail.verdict] += max(1, call.weight)
        return out

    def spend(self) -> Dict[str, float]:
        out = {v: 0.0 for v in VERDICT_ORDER}
        for call, detail in self.pairs:
            out[detail.verdict] += self.cost_of(call)[0]
        return out

    @property
    def total_spend(self) -> float:
        return sum(self.spend().values())

    @property
    def migratable_spend(self) -> float:
        s = self.spend()
        return s["likely"] + s["maybe"]

    def savings(self) -> Dict[str, float]:
        return {
            "conservative": _savings(self.migratable_spend, self.divisor),
            "vendor_claim": _savings(self.migratable_spend, self.divisor_optimistic),
        }

    def cost_provenance(self) -> Dict[str, int]:
        logged = estimated = 0
        for call, _ in self.pairs:
            if call.logged_cost_usd is not None:
                logged += max(1, call.weight)
            else:
                estimated += max(1, call.weight)
        return {"logged": logged, "estimated": estimated}

    def unknown_models(self) -> List[str]:
        seen = set()
        for call, _ in self.pairs:
            _, key, fallback, _ = self.cost_of(call)
            if fallback:
                seen.add(f"{call.model} → priced at {key}")
        return sorted(seen)

    def signal_tally(self) -> Dict[str, int]:
        tally = {name: 0 for name in WEIGHTS}
        for call, detail in self.pairs:
            w = max(1, call.weight)
            for name, value in detail.signals.items():
                if value > 0:
                    tally[name] = tally.get(name, 0) + w
        return tally

    def duplication_rates(self) -> Dict[str, float]:
        stats = corpus_stats([c for c, _ in self.pairs])
        return {m: round(s["dup_rate"], 3) for m, s in sorted(stats.items())}

    def top_candidates(self, n: int = 25) -> List[Pair]:
        ranked = sorted(
            self.pairs, key=lambda p: (p[1].score, self.cost_of(p[0])[0]), reverse=True
        )
        return ranked[:n]

    def models_table(self) -> List[Dict]:
        rows: Dict[str, Dict] = {}
        for call, detail in self.pairs:
            w = max(1, call.weight)
            row = rows.setdefault(
                call.model, {"model": call.model, "calls": 0, "cost": 0.0, "likely": 0}
            )
            row["calls"] += w
            row["cost"] += self.cost_of(call)[0]
            if detail.verdict == "likely":
                row["likely"] += w
        return sorted(rows.values(), key=lambda r: -r["cost"])

    # ------------------------------------------------------------------ Jev map sketches

    def jev_maps(self) -> List[Dict]:
        items = [
            MapItem(
                prompt=c.prompt_excerpt,
                output=c.output_excerpt,
                score=d.score,
                weight=max(1, c.weight),
                origin=c.source,
            )
            for c, d in self.pairs
            if d.verdict == "likely"
        ]
        return [
            {
                "role": m.role,
                "template": m.template,
                "kind": m.kind,
                "options": m.options,
                "note": m.note,
                "example": m.example,
                "calls": m.calls,
                "score_range": m.score_range,
            }
            for m in build_maps(items)
        ]


def run_audit(
    paths: List[Path],
    fmt: str = "auto",
    likely_threshold: float = LIKELY_THRESHOLD,
    maybe_threshold: float = MAYBE_THRESHOLD,
    price_file: Optional[Path] = None,
    divisor: int = DEFAULT_DIVISOR,
    divisor_optimistic: int = VENDOR_CLAIM_DIVISOR,
) -> Audit:
    overrides = load_price_file(price_file) if price_file else None

    calls: List[LlmCall] = []
    skipped = 0
    for path in paths:
        file_calls, file_skipped = parse_file(path, fmt=fmt)
        calls.extend(file_calls)
        skipped += file_skipped

    from .heuristics import corpus_stats as _cs

    stats = _cs(calls)
    pairs: List[Pair] = []
    for call in calls:
        detail = score_call(call, stats)
        if not call.prompt_excerpt and not call.output_excerpt:
            detail.verdict = "insufficient"
        elif detail.score >= likely_threshold:
            detail.verdict = "likely"
        elif detail.score >= maybe_threshold:
            detail.verdict = "maybe"
        else:
            detail.verdict = "unlikely"
        pairs.append((call, detail))

    audit = Audit(
        files=[str(p) for p in paths],
        pairs=pairs,
        skipped_lines=skipped,
        divisor=divisor,
        divisor_optimistic=divisor_optimistic,
    )
    audit.price_overrides = overrides
    return audit
