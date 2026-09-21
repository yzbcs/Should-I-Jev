from __future__ import annotations

import unittest
from importlib.resources import files
from pathlib import Path

from should_i_jev.calibration import (
    brier,
    coverage_table,
    ece,
    load_decisions,
    mce,
    reliability_bins,
    risk_coverage,
    summarize,
)

FIXTURES = Path(str(files("should_i_jev").joinpath("fixtures")))


def rec(p, correct, question="q", model="m"):
    from should_i_jev.calibration import DecisionRecord

    return DecisionRecord(p=p, correct=correct, model=model, question=question)


class MetricsTests(unittest.TestCase):
    def test_perfectly_calibrated(self):
        records = [rec(1.0, True) for _ in range(50)] + [rec(0.0, False) for _ in range(50)]
        bins = reliability_bins(records)
        self.assertAlmostEqual(ece(bins, 100), 0.0, places=6)
        self.assertAlmostEqual(mce(bins), 0.0, places=6)
        self.assertAlmostEqual(brier(records), 0.0, places=6)

    def test_fully_miscalibrated(self):
        records = [rec(1.0, False) for _ in range(100)]
        bins = reliability_bins(records)
        self.assertAlmostEqual(ece(bins, 100), 1.0, places=6)
        self.assertAlmostEqual(brier(records), 1.0, places=6)

    def test_known_ece(self):
        # 10 items in bin [0.8,0.9): conf 0.8, acc 0.5 -> ECE = 1 * |0.5-0.8| = 0.3
        records = [rec(0.8, True)] * 5 + [rec(0.8, False)] * 5
        bins = reliability_bins(records)
        self.assertAlmostEqual(ece(bins, 10), 0.3, places=6)
        self.assertAlmostEqual(mce(bins), 0.3, places=6)

    def test_bins_are_exhaustive(self):
        records = [rec(0.0, False), rec(0.999, True), rec(1.0, True), rec(0.5, True)]
        bins = reliability_bins(records, n_bins=10)
        self.assertEqual(sum(b.n for b in bins), 4)
        # p=1.0 must land in the last bin, not out of range
        self.assertEqual(bins[-1].n, 2)

    def test_brier_value(self):
        records = [rec(0.8, True), rec(0.6, False)]
        # (0.8-1)^2 + (0.6-0)^2 = 0.04 + 0.36 = 0.40 / 2
        self.assertAlmostEqual(brier(records), 0.2, places=6)

    def test_risk_coverage_monotone_coverage(self):
        records = [rec(0.9, True), rec(0.8, False), rec(0.7, True)]
        rc = risk_coverage(records)
        self.assertEqual([p["coverage"] for p in rc], [1 / 3, 2 / 3, 1.0])
        self.assertEqual(rc[0]["sel_acc"], 1.0)
        self.assertEqual(rc[-1]["sel_acc"], 2 / 3)

    def test_coverage_table(self):
        records = [rec(0.9, True), rec(0.8, True), rec(0.1, False), rec(0.1, False)]
        table = coverage_table(records)
        self.assertAlmostEqual(table[0.5], 1.0)   # top 2 are both correct
        self.assertAlmostEqual(table[1.0], 0.5)  # everything answered


class LoaderTests(unittest.TestCase):
    def test_aliases_and_skips(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "d.jsonl"
            p.write_text(
                "\n".join(
                    [
                        json.dumps({"prob": 0.7, "outcome": True, "model": "jev-latest", "question": "q1"}),
                        json.dumps({"confidence": 0.2, "is_correct": "false"}),
                        json.dumps({"p": 1.4, "correct": True}),      # invalid p -> skipped
                        json.dumps({"p": 0.5}),                        # no correct -> skipped
                        "not json",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            records, skipped = load_decisions(p)
            self.assertEqual(len(records), 2)
            self.assertEqual(skipped, 3)
            self.assertAlmostEqual(records[0].p, 0.7)
            self.assertIs(records[1].correct, False)

    def test_fixture_datasets(self):
        jev, sj = load_decisions(FIXTURES / "calibration" / "decisions_jev.jsonl")
        llm, sl = load_decisions(FIXTURES / "calibration" / "decisions_llm.jsonl")
        self.assertEqual(len(jev), 400)
        self.assertEqual(len(llm), 400)
        self.assertEqual((sj, sl), (0, 0))
        s_jev, s_llm = summarize(jev), summarize(llm)
        # the story the fixtures tell: jev calibrated, llm overconfident
        self.assertLess(s_jev["ece"], 0.08)
        self.assertGreater(s_llm["ece"], 0.12)
        self.assertGreater(s_jev["accuracy"], s_llm["accuracy"])
        self.assertGreater(len(s_jev["groups"]), 1)


if __name__ == "__main__":
    unittest.main()
