from __future__ import annotations

import unittest

from should_i_jev.heuristics import (
    LIKELY_THRESHOLD,
    MAYBE_THRESHOLD,
    corpus_stats,
    score_call,
)
from should_i_jev.models import LlmCall


def make_call(**kw) -> LlmCall:
    defaults = dict(
        call_id="t",
        source="test",
        format="generic",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=3,
        prompt_excerpt="Classify this ticket into billing or technical: 'charged twice'",
        output_excerpt="billing",
    )
    defaults.update(kw)
    return LlmCall(**defaults)


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.stats = corpus_stats([])

    def test_classify_call_is_likely(self):
        detail = score_call(make_call(), self.stats)
        self.assertGreaterEqual(detail.score, LIKELY_THRESHOLD)
        self.assertEqual(detail.verdict, "likely")
        self.assertAlmostEqual(detail.signals["short_output"], 1.0)
        self.assertGreater(detail.signals["structured_output"], 0)
        self.assertGreater(detail.signals["decision_language"], 0)

    def test_long_generative_call_is_unlikely(self):
        detail = score_call(
            make_call(
                prompt_excerpt="Write a detailed blog post about remote work trends",
                output_excerpt="Remote work has reshaped ..." + "lots of prose. " * 30,
                input_tokens=3000,
                output_tokens=900,
            ),
            self.stats,
        )
        self.assertEqual(detail.verdict, "unlikely")
        self.assertLess(detail.score, MAYBE_THRESHOLD)

    def test_bool_output_full_structure_signal(self):
        detail = score_call(
            make_call(prompt_excerpt="Is this spam? Answer yes or no.", output_excerpt="yes"),
            self.stats,
        )
        self.assertAlmostEqual(detail.signals["structured_output"], 1.0)
        self.assertEqual(detail.verdict, "likely")

    def test_numeric_output(self):
        detail = score_call(
            make_call(prompt_excerpt="Rate the urgency from 1 to 5: outage", output_excerpt="5"),
            self.stats,
        )
        self.assertAlmostEqual(detail.signals["structured_output"], 1.0)

    def test_valid_json_output(self):
        detail = score_call(
            make_call(prompt_excerpt="Extract fields as JSON", output_excerpt='{"a": 1}'),
            self.stats,
        )
        self.assertAlmostEqual(detail.signals["structured_output"], 1.0)

    def test_broken_json_gets_partial_credit(self):
        detail = score_call(
            make_call(prompt_excerpt="Extract fields as JSON", output_excerpt='{"a": 1'),
            self.stats,
        )
        self.assertAlmostEqual(detail.signals["structured_output"], 0.5)

    def test_duplicate_outputs_boost_diversity(self):
        calls = [make_call(output_excerpt="yes"), make_call(output_excerpt="yes")]
        stats = corpus_stats(calls)
        detail = score_call(calls[0], stats)
        self.assertAlmostEqual(detail.signals["low_output_diversity"], 0.6)

    def test_singleton_output_no_diversity(self):
        detail = score_call(make_call(), corpus_stats([make_call()]))
        self.assertAlmostEqual(detail.signals["low_output_diversity"], 0.0)

    def test_question_shape(self):
        detail = score_call(
            make_call(prompt_excerpt="Should this ticket be escalated to on-call?", output_excerpt="no"),
            self.stats,
        )
        self.assertAlmostEqual(detail.signals["question_shape"], 1.0)

    def test_token_only_rows_marked_insufficient(self):
        # usage exports carry no text: token shape alone must not claim a verdict
        detail = score_call(
            make_call(prompt_excerpt="", output_excerpt="", input_tokens=310, output_tokens=4),
            self.stats,
        )
        self.assertEqual(detail.verdict, "insufficient")
        self.assertLess(detail.score, LIKELY_THRESHOLD)

    def test_generative_penalty_only_without_decision_verbs(self):
        base = score_call(
            make_call(prompt_excerpt="Draft a friendly follow-up email to a customer"),
            self.stats,
        )
        penalized = score_call(
            make_call(prompt_excerpt="Draft a friendly follow-up email and classify the tone"),
            self.stats,
        )
        # penalty applies only when no decision verb is present
        self.assertGreater(penalized.score, base.score)


if __name__ == "__main__":
    unittest.main()
