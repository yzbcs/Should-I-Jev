from __future__ import annotations

import unittest
from importlib.resources import files
from pathlib import Path

from should_i_jev.audit import run_audit
from should_i_jev.report import redact_text, render_markdown

FIXTURES = Path(str(files("should_i_jev").joinpath("fixtures")))


def demo_audit():
    paths = sorted(
        p for pattern in ("*.jsonl", "*.csv")
        for p in FIXTURES.glob(pattern)
    )
    return run_audit(paths)


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = demo_audit()

    def test_all_fixtures_parsed(self):
        # 18 litellm + 15 langfuse + 6 rollup rows + usage rows expanded by request_count
        anthropic_weights = [260, 140, 22, 415, 15, 18, 322]
        openai_weights = [412, 388, 47, 530, 12, 203, 471, 95, 8, 356]
        rollup_weights = [18400, 92600, 41200, 8300, 15700, 6400]
        rows = sum(max(1, c.weight) for c, _ in self.audit.pairs)
        self.assertEqual(
            rows,
            18 + 15 + sum(anthropic_weights) + sum(openai_weights) + sum(rollup_weights),
        )

    def test_verdicts_exist(self):
        counts = self.audit.counts()
        self.assertIn("likely", counts)
        self.assertGreater(counts["likely"], 0)
        self.assertGreater(counts["insufficient"], 0)

    def test_insufficient_excluded_from_migratable(self):
        spend = self.audit.spend()
        self.assertAlmostEqual(
            self.audit.migratable_spend, spend["likely"] + spend["maybe"]
        )

    def test_spend_positive(self):
        self.assertGreater(self.audit.total_spend, 0)
        self.assertLessEqual(self.audit.migratable_spend, self.audit.total_spend)

    def test_jev_maps_generated(self):
        maps = self.audit.jev_maps()
        self.assertTrue(maps)
        roles = {m["role"] for m in maps}
        self.assertIn("Classifier", roles)

    def test_costs_memoized_consistent(self):
        for call, _ in self.audit.pairs[:20]:
            self.assertAlmostEqual(self.audit.cost_of(call)[0], self.audit.cost_of(call)[0])


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.md = render_markdown(demo_audit(), top_n=10)

    def test_sections_present(self):
        for heading in (
            "# JEV migration audit",
            "## TL;DR",
            "## Verdict breakdown",
            "## Signals observed",
            "## Top migration candidates",
            "## Suggested JEV maps",
            "## Cost & savings methodology",
            "## Privacy",
            "## Disclaimers",
        ):
            self.assertIn(heading, self.md)

    def test_redaction(self):
        self.assertNotIn("sk-demo0123456789abcdef", self.md)
        self.assertNotIn("jane.doe@example.com", self.md)
        self.assertNotIn("jane.doe", self.md)
        self.assertIn("[REDACTED@email]", self.md)

    def test_jev_map_examples_are_redacted(self):
        section = self.md.split("## Suggested JEV maps", 1)[1]
        self.assertNotIn("@example.com", section)


class RedactTests(unittest.TestCase):
    def test_patterns(self):
        scrubbed = redact_text(
            "key sk-abcdef1234567890XYZ and mail a.b@corp.io and hex "
            "deadbeefdeadbeefdeadbeefdeadbeef and password: hunter2secret and bearer abc123"
        )
        self.assertNotIn("sk-abcdef1234567890XYZ", scrubbed)
        self.assertNotIn("a.b@corp.io", scrubbed)
        self.assertNotIn("deadbeefdeadbeefdeadbeefdeadbeef", scrubbed)
        self.assertNotIn("hunter2secret", scrubbed)
        self.assertNotIn("abc123", scrubbed)

    def test_plain_language_not_clobbered(self):
        # "password step" in a sentence is not a credential pair
        text = "How to reset your API password step by step with screenshots"
        self.assertEqual(redact_text(text), text)


if __name__ == "__main__":
    unittest.main()
