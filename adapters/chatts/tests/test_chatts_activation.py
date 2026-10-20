"""Installed ChatTS entry-point activation and import isolation regressions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from gymts import GymTS


BASE = Path(__file__).resolve().parents[1]


class ChatTSActivationTests(unittest.TestCase):
    def test_core_run_and_discovery_succeed_when_chatts_import_is_blocked(self):
        script = '''
import importlib.abc
import json
from pathlib import Path
import sys
class BlockChatTS(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "gymts_chatts" or fullname.startswith("gymts_chatts."):
            raise ModuleNotFoundError("ChatTS is deliberately unavailable")
sys.meta_path.insert(0, BlockChatTS())
from gymts import GymTS
with GymTS(sys.argv[1]) as gym:
    assert any(item["name"] == "chatts" for item in gym.available_integrations())
    assert not any(name.startswith("gymts_chatts") for name in sys.modules)
    spec = json.loads(Path(sys.argv[2]).read_text())
    assert gym.validate(spec)["valid"]
    assert gym.run(spec)["status"] == "succeeded"
    try:
        gym.enable_integration("chatts")
    except Exception as error:
        assert error.code == "unsupported_capability", repr(error)
    else:
        raise AssertionError("Explicit missing integration must fail")
    assert gym.run(spec)["status"] == "succeeded"
'''
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, "-B", "-c", script, root,
                                     str(BASE / "tests" / "fixtures" / "forecast_experiment.json")],
                                    cwd=BASE, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_text_adapter_import_does_not_load_native_candidate(self):
        script = '''
import importlib.abc
import sys
class BlockNativeCandidate(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "gymts_chatts.candidate":
            raise ModuleNotFoundError("Native ChatTS adapter is deliberately unavailable")
sys.meta_path.insert(0, BlockNativeCandidate())
from gymts_chatts.text_candidate import TextLLMHTTPCandidate
from gymts.http_candidate import FrozenJSONHTTPCandidate
assert TextLLMHTTPCandidate.__bases__ == (FrozenJSONHTTPCandidate,)
assert "gymts_chatts.candidate" not in sys.modules
'''
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=BASE,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_explicit_registration_and_repeated_enable_preserve_v1_components(self):
        with tempfile.TemporaryDirectory() as root, GymTS(root, integrations=("chatts", "chatts")) as gym:
            self.assertEqual(("chatts",), gym.enabled_integrations)
            self.assertEqual("chatts-http", gym.registries.candidates.resolve(
                "chatts-http", "1.0.0")["component_ref"]["name"])
            self.assertEqual("chatts-text-http", gym.registries.candidates.resolve(
                "chatts-text-http", "1.0.0")["component_ref"]["name"])
            gym.enable_integration("chatts")
            self.assertEqual(("chatts",), gym.enabled_integrations)


if __name__ == "__main__":
    unittest.main()
