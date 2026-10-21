"""Synthetic syntax-only cases; no private references or reward-based selection."""
import hashlib
import unittest
from gymts_areal.codec import project_completion

SUMMARY = '{"mean":1.25,"last":2,"min":-1,"max":3}'


class AnswerCodec(unittest.TestCase):
    def test_terminal_latex_wrappers_and_punctuation_preserve_numeric_value(self):
        for native in (r"Reason \(\boxed{1,024}\).", r"Reason \[\boxed{1,024}\]", r"Reason $\boxed{1,024}$.", r"Reason \boxed{1,024}!"):
            text = native + "<native-eos>"
            projected, audit = project_completion(text, "gsm8k.numeric", ["<native-eos>"])
            self.assertEqual(projected, "#### 1024")
            self.assertEqual(audit["source_format"], "terminal_boxed")
            self.assertEqual(audit["native_text_sha256"], hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(audit["projected_text_sha256"], hashlib.sha256(projected.encode()).hexdigest())

    def test_last_box_is_deterministic_and_never_falls_back_to_an_earlier_value(self):
        self.assertEqual(project_completion(r"Intermediate \boxed{9}; final \boxed{2}.", "gsm8k.numeric")[0], "#### 2")
        for text in (r"\boxed{2} then \boxed{2+3}", r"\boxed{2} then \boxed{3", r"\boxed{2} people", r"\boxed{2} trailing"):
            self.assertEqual(project_completion(text, "gsm8k.numeric")[0], text)
            self.assertFalse(project_completion(text, "gsm8k.numeric")[1]["converted"])

    def test_one_explicit_json_block_is_projected_without_repairing_fields(self):
        native = "Analysis.\n```json\n" + SUMMARY + "\n```\nThis is the final answer."
        projected, audit = project_completion(native, "chatts.numeric_summary")
        self.assertEqual(projected, SUMMARY)
        self.assertEqual(audit["source_format"], "unique_explicit_json_answer_block")
        self.assertEqual(project_completion(r"\boxed{" + SUMMARY + r"}.", "chatts.numeric_summary")[0], SUMMARY)

    def test_ambiguous_blocks_nested_values_and_invalid_last_box_are_rejected(self):
        fence = "```json\n" + SUMMARY + "\n```"
        bad = (fence + "\n" + fence,
               "```json\n" + SUMMARY + "\n" + SUMMARY + "\n```",
               '```json\n{"mean":{"value":1},"last":2,"min":-1,"max":3}\n```',
               '```json\n{"mean":1,"mean":2,"last":2,"min":-1,"max":3}\n```',
               fence + r" final \boxed{invalid}",
               '```json\n{"mean":NaN,"last":2,"min":-1,"max":3}\n```')
        for text in bad:
            with self.subTest(text=text):
                projected, audit = project_completion(text, "chatts.numeric_summary")
                self.assertEqual(projected, text)
                self.assertFalse(audit["converted"])
