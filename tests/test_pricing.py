from __future__ import annotations

import unittest

from should_i_jev.models import LlmCall
from should_i_jev.pricing import (
    estimate_cost,
    load_price_file,
    lookup_price,
    normalize_model,
    savings,
)


class ModelNormalization(unittest.TestCase):
    def test_strips_provider_prefix_and_date(self):
        self.assertEqual(normalize_model("openai/gpt-4o-2024-08-06"), "gpt-4o")
        self.assertEqual(normalize_model("Anthropic/Claude-3-5-Haiku-20241022"), "claude-3-5-haiku")
        self.assertEqual(normalize_model("gpt-4o-mini"), "gpt-4o-mini")

    def test_lookup_exact_and_prefix(self):
        rate_in, rate_out, key, fallback = lookup_price("gpt-4o-2024-08-06")
        self.assertFalse(fallback)
        self.assertEqual(key, "gpt-4o")
        self.assertEqual((rate_in, rate_out), (2.50, 10.00))

    def test_unknown_model_falls_back_to_median(self):
        _, _, key, fallback = lookup_price("mystery-model-v9")
        self.assertTrue(fallback)
        self.assertIn("median", key)

    def test_overrides_win(self):
        rates = {"my-finetune": [1.0, 2.0]}
        rate_in, rate_out, key, fallback = lookup_price("my-finetune-20260101", overrides=rates)
        self.assertFalse(fallback)
        self.assertEqual((rate_in, rate_out), (1.0, 2.0))


class CostEstimation(unittest.TestCase):
    def _call(self, **kw):
        defaults = dict(call_id="t", source="s", format="generic", model="gpt-4o")
        defaults.update(kw)
        return LlmCall(**defaults)

    def test_logged_cost_is_row_total_not_multiplied(self):
        # logged costs (usage exports, response_cost, totalCost) are already row totals
        usd, key, _, _ = estimate_cost(self._call(logged_cost_usd=0.5, weight=3))
        self.assertAlmostEqual(usd, 0.5)
        self.assertEqual(key, "(logged)")

    def test_estimated_cost_multiplied_by_weight(self):
        usd, _, _, _ = estimate_cost(
            self._call(input_tokens=1_000_000, output_tokens=0, weight=3)
        )
        self.assertAlmostEqual(usd, 7.50)

    def test_token_math(self):
        usd, key, fallback, _ = estimate_cost(
            self._call(input_tokens=1_000_000, output_tokens=1_000_000)
        )
        self.assertFalse(fallback)
        self.assertAlmostEqual(usd, 2.50 + 10.00)

    def test_unknown_model_flagged(self):
        _, _, fallback, _ = estimate_cost(self._call(model="mystery-v9", input_tokens=10))
        self.assertTrue(fallback)

    def test_text_approximation_when_tokens_missing(self):
        usd, _, _, approx = estimate_cost(
            self._call(prompt_excerpt="x" * 400, output_excerpt="y" * 100)
        )
        self.assertTrue(approx)
        self.assertGreater(usd, 0)

    def test_savings_formula(self):
        self.assertAlmostEqual(savings(100.0, 100), 99.0)
        self.assertAlmostEqual(savings(100.0, 400), 99.75)


class PriceFile(unittest.TestCase):
    def test_load(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "prices.json"
            p.write_text(json.dumps({"gpt-4o": [3.0, 12.0]}), encoding="utf-8")
            rates = load_price_file(p)
            self.assertEqual(rates["gpt-4o"], (3.0, 12.0))


if __name__ == "__main__":
    unittest.main()
