"""Synthetic metadata-only contracts; real tokenizer equality is an acceptance check."""
import copy
import hashlib
import json
import unittest

from gymts_areal.checkpoint import TOKENIZER_PROJECTION, tokenizer_metadata_projection


class TokenizerProjection(unittest.TestCase):
    def assets(self, config):
        return {"assets/tokenizer_config.json": json.dumps(config).encode(),
            "assets/tokenizer.json": b"unchanged tokenizer fixture", "assets/chat_template.jinja": b"unchanged template",
            "adapter/adapter_model.safetensors": b"unchanged weight fixture"}

    def test_ordered_special_tokens_are_preserved_without_rewriting_other_assets(self):
        tokens = ["<test-a>", "<test-b>", "<test-c>"]
        source = {"extra_special_tokens": tokens, "chat_template": "fixture template", "eos_token": "<test-b>",
            "added_tokens_decoder": {"17": {"content": "<test-a>", "special": True}}}
        assets = self.assets(source)
        original = copy.deepcopy(assets)
        result, audit = tokenizer_metadata_projection(assets, "hf4")
        config = json.loads(result["assets/tokenizer_config.json"])
        self.assertEqual(config["additional_special_tokens"], tokens)
        self.assertEqual(config["extra_special_tokens"], {})
        for key in source:
            if key != "extra_special_tokens": self.assertEqual(config[key], source[key])
        self.assertEqual(assets, original)
        self.assertTrue(all(result[key] == value for key, value in assets.items() if key != "assets/tokenizer_config.json"))
        self.assertEqual(audit["version"], TOKENIZER_PROJECTION)
        self.assertEqual(audit["ordered_special_tokens"], tokens)
        self.assertEqual(audit["special_token_count"], 3)
        self.assertTrue(audit["applied"])
        self.assertEqual(audit["source_config_sha256"], hashlib.sha256(original["assets/tokenizer_config.json"]).hexdigest())
        self.assertNotEqual(audit["source_config_sha256"], audit["deployment_config_sha256"])

    def test_native_and_already_compatible_metadata_remain_byte_identical(self):
        for target, config in (("native", {"extra_special_tokens": ["<test>"]}),
                ("hf4", {"extra_special_tokens": {"named_token": "<test>"}}), ("hf4", {"additional_special_tokens": ["<test>"]})):
            with self.subTest(target=target, config=config):
                assets = self.assets(config)
                result, audit = tokenizer_metadata_projection(assets, target)
                self.assertEqual(result, assets)
                self.assertFalse(audit["applied"])

    def test_conflicting_or_unsupported_token_metadata_is_rejected(self):
        configs = [{"extra_special_tokens": ["<test-a>"], "additional_special_tokens": ["<test-b>"]},
            {"extra_special_tokens": ["<test>", "<test>"]}, {"extra_special_tokens": [{"content": "<test>"}]},
            {"extra_special_tokens": "<test>"}]
        for config in configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                tokenizer_metadata_projection(self.assets(config), "hf4")
        with self.assertRaises(ValueError): tokenizer_metadata_projection(self.assets({}), "unknown")
