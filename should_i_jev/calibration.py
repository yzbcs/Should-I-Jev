"""Calibration metrics for decision models — ECE, MCE, Brier, risk-coverage.

Input is a JSONL of decision records, one per answered question::

    {"p": 0.82, "correct": true, "model": "jev-latest", "question": "ticket-router"}

``p`` is the probability the model assigned to the answer it gave — Jev
returns this natively; for LLMs use the top-choice probability. ``correct`` is
the ground-truth hit flag. Common aliases are accepted; records without a
usable (p, correct) pair are skipped and counted.

Everything is pure math on local data; no network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_P_KEYS = ("p", "prob", "probability", "confidence", "conf")
_CORRECT_KEYS = ("correct", "is_correct", "outcome", "label_ok", "hit")
_TRUE_WORDS = {"true", "yes", "y", "1", "hit", "correct"}
_FALSE_WORDS = {"false", "no", "n", "0", "miss", "incorrect"}

DEFAULT_BINS = 10
COVERAGE_LEVELS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0)


@dataclass
class DecisionRecord:
    p: float
    correct: bool
    model: str = "unknown"
    question: str = ""


@dataclass
class ReliabilityBin:
    lo: float
    hi: float
    n: int = 0
    conf: float = 0.0          # mean predicted probability in the bin
    acc: float = 0.0           # empirical accuracy in the bin

    @property
    def gap(self) -> float:
        return self.acc - self.conf

    @property
    def abs_gap(self) -> float:
        return abs(self.acc - self.conf)


def _as_float(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _as_bool(x) -> Optional[bool]:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        low = x.strip().lower()
        if low in _TRUE_WORDS:
            return True
        if low in _FALSE_WORDS:
            return False
    return None


def load_decisions(path) -> Tuple[List[DecisionRecord], int]:
    """Parse one JSONL file into records. Returns (records, skipped_lines)."""
    records: List[DecisionRecord] = []
    skipped = 0
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(rec, dict):
            skipped += 1
            continue
        p = next((_as_float(rec[k]) for k in _P_KEYS if k in rec), None)
        correct = next((_as_bool(rec[k]) for k in _CORRECT_KEYS if k in rec), None)
        if p is None or not (0.0 <= p <= 1.0) or correct is None:
            skipped += 1
            continue
        model = rec.get("model") if isinstance(rec.get("model"), str) else "unknown"
        question = rec.get("question") if isinstance(rec.get("question"), str) else ""
        records.append(DecisionRecord(p=p, correct=correct, model=model, question=question))
    return records, skipped


def reliability_bins(records: List[DecisionRecord], n_bins: int = DEFAULT_BINS) -> List[ReliabilityBin]:
    bins = [ReliabilityBin(lo=i / n_bins, hi=(i + 1) / n_bins) for i in range(n_bins)]
    sums = [[0.0, 0] for _ in range(n_bins)]  # [sum_p, n_correct]
    for r in records:
        idx = min(int(r.p * n_bins), n_bins - 1)
        sums[idx][0] += r.p
        sums[idx][1] += 1 if r.correct else 0
        bins[idx].n += 1
    for i, b in enumerate(bins):
        if b.n:
            b.conf = sums[i][0] / b.n
            b.acc = sums[i][1] / b.n
    return bins


def ece(bins: List[ReliabilityBin], n_total: int) -> float:
    if not n_total:
        return 0.0
    return sum(b.n / n_total * b.abs_gap for b in bins)


def mce(bins: List[ReliabilityBin]) -> float:
    nonempty = [b for b in bins if b.n]
    return max((b.abs_gap for b in nonempty), default=0.0)


def brier(records: List[DecisionRecord]) -> float:
    if not records:
        return 0.0
    return sum((r.p - (1.0 if r.correct else 0.0)) ** 2 for r in records) / len(records)


def risk_coverage(records: List[DecisionRecord]) -> List[Dict]:
    """Selective-accuracy curve: answer everything above a confidence cut, abstain below."""
    ordered = sorted(records, key=lambda r: -r.p)
    n = len(ordered)
    hits = 0
    points: List[Dict] = []
    for k, r in enumerate(ordered, start=1):
        hits += 1 if r.correct else 0
        points.append(
            {
                "k": k,
                "coverage": k / n,
                "sel_acc": hits / k,
                "threshold": r.p,
            }
        )
    return points


def coverage_table(
    records: List[DecisionRecord], levels=COVERAGE_LEVELS
) -> Dict[float, Optional[float]]:
    rc = risk_coverage(records)
    table: Dict[float, Optional[float]] = {}
    for level in levels:
        pt = next((p for p in rc if p["coverage"] >= level - 1e-9), None)
        table[level] = pt["sel_acc"] if pt else None
    return table


def group_summary(records: List[DecisionRecord], n_bins: int = DEFAULT_BINS) -> List[Dict]:
    groups: Dict[str, List[DecisionRecord]] = {}
    for r in records:
        key = r.question or "(unlabeled)"
        groups.setdefault(key, []).append(r)
    rows = []
    for name, recs in groups.items():
        bins = reliability_bins(recs, n_bins)
        rows.append(
            {
                "question": name,
                "n": len(recs),
                "acc": sum(1 for r in recs if r.correct) / len(recs),
                "ece": ece(bins, len(recs)),
                "avg_p": sum(r.p for r in recs) / len(recs),
            }
        )
    rows.sort(key=lambda r: -r["n"])
    return rows


def summarize(
    records: List[DecisionRecord], n_bins: int = DEFAULT_BINS, rc_points: int = 60
) -> Dict:
    n = len(records)
    bins = reliability_bins(records, n_bins)
    rc = risk_coverage(records)
    step = max(1, len(rc) // rc_points)
    return {
        "n": n,
        "model": (records[0].model if records else "unknown"),
        "accuracy": (sum(1 for r in records if r.correct) / n) if n else 0.0,
        "avg_p": (sum(r.p for r in records) / n) if n else 0.0,
        "ece": ece(bins, n),
        "mce": mce(bins),
        "brier": brier(records),
        "bins": bins,
        "coverage": coverage_table(records),
        "rc": rc[::step] + ([rc[-1]] if rc and (rc[::step] or [None])[-1] is not rc[-1] else []),
        "groups": group_summary(records, n_bins),
    }
