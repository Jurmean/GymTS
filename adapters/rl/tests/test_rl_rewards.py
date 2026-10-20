"""Verifiable rewards reject ambiguous answers and keep gold out of parsing."""

import json
import math
import unittest

from gymts_rl.rewards import extract_gsm8k_answer, parse_completion, score_completion, trl_reward


class RLRewardsTest(unittest.TestCase):
    def test_numeric_answer_uses_last_line_and_one_marker(self):
        self.assertEqual(extract_gsm8k_answer("Work out the arithmetic.\n#### 1,234\n"), ("1234", None))
        for text in ("#### 42\nActually, another sentence", "#### 41\n#### 42", "The result is 42", "#### 42 or 43", "#### NaN", "#### inf", "#### 1e3"):
            with self.subTest(text=text):
                self.assertIsNotNone(extract_gsm8k_answer(text)[1])

    def test_decimal_comparison_is_exact_and_not_float_rounded(self):
        spec = {"kind": "gsm8k_numeric", "ground_truth": "9007199254740993"}
        self.assertEqual(score_completion("#### 9007199254740993", spec)["reward"], 1)
        self.assertEqual(score_completion("#### 9007199254740992", spec)["reward"], 0)
        self.assertEqual(score_completion("#### -0.00", dict(spec, ground_truth="0"))["reward"], 1)

    def test_format_validity_is_separate_from_correctness(self):
        spec = {"kind": "gsm8k_numeric", "ground_truth": "42"}
        wrong = score_completion("#### 41", spec)
        self.assertTrue(wrong["format_valid"])
        self.assertFalse(wrong["correct"])
        self.assertEqual(wrong["reason"], "incorrect_answer")
        self.assertFalse(score_completion("42", spec)["format_valid"])

    def test_numeric_summary_strictly_rejects_duplicate_extra_boolean_and_nonfinite(self):
        for text in ('{"mean":1,"min":0,"max":2,"last":1,"mean":1}',
                     '{"mean":1,"min":0,"max":2,"last":1,"extra":1}',
                     '{"mean":true,"min":0,"max":2,"last":1}',
                     '{"mean":NaN,"min":0,"max":2,"last":1}',
                     '{"mean":1e999,"min":0,"max":2,"last":1}',
                     '```json\n{"mean":1,"min":0,"max":2,"last":1}\n```'):
            with self.subTest(text=text):
                self.assertIsNotNone(parse_completion(text, "chatts.numeric_summary")[1])

    def test_summary_reward_is_bounded_and_reports_raw_error(self):
        target = {"mean": 1., "min": 0., "max": 2., "last": 1.}
        spec = {"kind": "numeric_summary", "ground_truth": target, "scale": 2., "atol": .001, "rtol": .001}
        correct = score_completion(json.dumps(target), spec)
        self.assertEqual(correct["reward"], 1)
        self.assertEqual(correct["error"], 0)
        wrong = score_completion(json.dumps({key: value + 2 for key, value in target.items()}), spec)
        self.assertEqual(wrong["error"], 2)
        self.assertEqual(wrong["reward"], .5)
        self.assertFalse(wrong["correct"])
        nearby = dict(target, mean=1.0005)
        self.assertTrue(score_completion(json.dumps(nearby), spec)["correct"])

    def test_extreme_finite_predictions_cannot_create_nonfinite_rewards(self):
        spec = {"kind": "numeric_summary", "ground_truth": {key: -1e308 for key in ("mean", "min", "max", "last")}}
        result = score_completion(json.dumps({key: 1e308 for key in spec["ground_truth"]}), spec)
        self.assertEqual(result["reward"], 0)
        json.dumps(result, allow_nan=False)

    def test_invalid_reward_specs_fail_instead_of_issuing_unearned_reward(self):
        for spec in ({"kind": "unknown"}, {"kind": "numeric_summary", "ground_truth": {"mean": 1}},
                     {"kind": "numeric_summary", "ground_truth": {key: 1 for key in ("mean", "min", "max", "last")}, "scale": 0}):
            with self.assertRaises(ValueError):
                score_completion('{"mean":1,"min":1,"max":1,"last":1}', spec)

    def test_trl_callable_supports_mixed_standard_and_conversational_batches(self):
        target = {"mean": 1, "min": 0, "max": 2, "last": 1}
        values = trl_reward(["#### 42", [{"role": "assistant", "content": json.dumps(target)}]],
            [{"kind": "gsm8k_numeric", "ground_truth": "42"}, {"kind": "numeric_summary", "ground_truth": target}], ignored_extra_column=True)
        self.assertEqual(values, [1., 1.])
        self.assertEqual(trl_reward(["#### 42"], [json.dumps({"kind": "gsm8k_numeric", "ground_truth": "42"})]), [1.])
        with self.assertRaises(ValueError):
            trl_reward(["#### 42"], [])

    def test_missing_ground_truth_never_turns_malformed_answer_into_measured_zero(self):
        with self.assertRaises(ValueError):
            score_completion("I do not know", {"kind": "gsm8k_numeric"})


if __name__ == "__main__":
    unittest.main()
