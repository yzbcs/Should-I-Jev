from __future__ import annotations

import unittest
from importlib.resources import files
from pathlib import Path

from should_i_jev.parsers import parse_file, sniff_format

FIXTURES = Path(str(files("should_i_jev").joinpath("fixtures")))


class ParserTests(unittest.TestCase):
    def test_litellm_fixture(self):
        calls, skipped = parse_file(FIXTURES / "litellm_logs.jsonl")
        self.assertEqual(skipped, 0)
        self.assertEqual(len(calls), 18)
        self.assertTrue(all(c.format == "litellm" for c in calls))
        first = calls[0]
        self.assertEqual(first.model, "gpt-4o-mini")
        self.assertEqual(first.input_tokens, 48)
        self.assertEqual(first.output_tokens, 3)
        self.assertIn("Route this ticket", first.prompt_excerpt)
        self.assertEqual(first.output_excerpt, "billing")
        self.assertAlmostEqual(first.logged_cost_usd, 0.0000192)

    def test_langfuse_fixture(self):
        calls, skipped = parse_file(FIXTURES / "langfuse_export.jsonl")
        self.assertEqual(skipped, 0)
        self.assertEqual(len(calls), 15)
        self.assertTrue(all(c.format == "langfuse" for c in calls))
        first = calls[0]
        self.assertEqual(first.model, "claude-3-5-haiku")
        self.assertEqual(first.input_tokens, 44)
        self.assertEqual(first.output_tokens, 2)
        self.assertEqual(first.output_excerpt, "bug")
        self.assertAlmostEqual(first.logged_cost_usd, 0.0000432)

    def test_openai_csv_fixture(self):
        calls, skipped = parse_file(FIXTURES / "openai_usage.csv")
        self.assertEqual(skipped, 0)
        self.assertEqual(len(calls), 10)
        self.assertTrue(all(c.format == "generic" for c in calls))
        first = calls[0]
        self.assertEqual(first.model, "gpt-4o-mini")
        self.assertEqual(first.weight, 412)
        self.assertEqual(first.input_tokens, 52)
        self.assertAlmostEqual(first.logged_cost_usd, 0.00396)

    def test_anthropic_jsonl_fixture(self):
        calls, skipped = parse_file(FIXTURES / "anthropic_usage.jsonl")
        self.assertEqual(skipped, 0)
        self.assertEqual(len(calls), 7)
        self.assertTrue(all(c.format == "generic" for c in calls))
        self.assertEqual(calls[0].weight, 260)

    def test_pipeline_rollup_fixture(self):
        calls, skipped = parse_file(FIXTURES / "pipeline_rollup.jsonl")
        self.assertEqual(skipped, 0)
        self.assertEqual(len(calls), 6)
        self.assertTrue(all(c.format == "generic" for c in calls))
        first = calls[0]
        self.assertEqual(first.model, "gpt-4o")
        self.assertEqual(first.weight, 18400)
        self.assertIn("Route this ticket", first.prompt_excerpt)
        self.assertEqual(first.output_excerpt, "billing")
        self.assertAlmostEqual(first.logged_cost_usd, 3.864)

    def test_json_array_file(self):
        tmp = FIXTURES.parent / "_tmp_array_test.json"
        tmp.write_text(
            '[{"model": "gpt-4o", "input_tokens": 10, "output_tokens": 2}]',
            encoding="utf-8",
        )
        try:
            calls, _ = parse_file(tmp)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].model, "gpt-4o")
        finally:
            tmp.unlink()

    def test_skips_bad_lines(self):
        tmp = FIXTURES.parent / "_tmp_bad_test.jsonl"
        tmp.write_text(
            '{"model": "gpt-4o", "input_tokens": 1, "output_tokens": 1}\n'
            "not json at all\n"
            "\n"
            '{"model": "gpt-4o", "input_tokens": 2, "output_tokens": 1}\n',
            encoding="utf-8",
        )
        try:
            calls, skipped = parse_file(tmp)
            self.assertEqual(len(calls), 2)
            self.assertEqual(skipped, 1)
        finally:
            tmp.unlink()

    def test_unsupported_extension_rejected(self):
        with self.assertRaises(ValueError):
            parse_file(FIXTURES / "does_not_exist.txt")

    def test_sniff_format(self):
        self.assertEqual(sniff_format([{"messages": [], "model": "x"}]), "litellm")
        self.assertEqual(sniff_format([{"type": "generation", "model": "x"}]), "langfuse")
        self.assertEqual(sniff_format([{"model": "x", "input_tokens": 1}]), "generic")


if __name__ == "__main__":
    unittest.main()
