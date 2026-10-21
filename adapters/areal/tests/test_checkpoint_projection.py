"""CPU checkpoint transport tests; fixtures are untrained, not RL acceptance."""
import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("torch") and importlib.util.find_spec("safetensors"),
                     "Optional native checkpoint dependencies are not installed")
class DeploymentProjection(unittest.TestCase):
    def test_exact_exported_values_and_original_bytes_are_preserved(self):
        import io
        import zipfile
        import torch
        from safetensors.torch import save, load
        from gymts_areal.checkpoint import archive_bytes, deployment_projection
        from gymts_rl.checkpoint import adapter_state_hash
        state = {"lora_a": torch.tensor([[0.125, -0.375]], dtype=torch.bfloat16),
                 "lora_b": torch.tensor([[0.3], [0.7]], dtype=torch.float16),
                 "lora_c": torch.tensor([0.2], dtype=torch.float32)}
        original_bytes = save(state)
        projected, audit = deployment_projection(state)
        self.assertTrue(all(row["round_trip_exact"] and row["exact_exported_value_promotion"] for row in audit))
        self.assertTrue(all(value.dtype == torch.float32 for value in projected.values()))
        self.assertNotEqual(adapter_state_hash(projected), adapter_state_hash(state))
        self.assertEqual(save(state), original_bytes)
        for name in state:
            self.assertTrue(torch.equal(projected[name].to(state[name].dtype), state[name]))
        self.assertEqual(adapter_state_hash(load(save(projected))), adapter_state_hash(projected))
        archived = archive_bytes({"adapter_model.safetensors": original_bytes})
        with zipfile.ZipFile(io.BytesIO(archived)) as archive:
            self.assertEqual(archive.read("adapter_model.safetensors"), original_bytes)
        self.assertEqual(archived, archive_bytes({"adapter_model.safetensors": original_bytes}))

    def test_nonfinite_native_weights_are_rejected(self):
        import torch
        from gymts_areal.checkpoint import deployment_projection
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            deployment_projection({"lora": torch.tensor([float("nan")], dtype=torch.bfloat16)})
