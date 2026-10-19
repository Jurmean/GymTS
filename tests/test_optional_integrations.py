"""Import isolation and explicit optional-registration regressions."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts.http_candidate import FrozenJSONHTTPCandidate
from gymts.integrations import available_integrations
from gymts.storage import ArtifactStore


BASE = Path(__file__).resolve().parents[1]


class OptionalIntegrationTests(unittest.TestCase):
    def test_core_run_and_discovery_succeed_when_chatts_import_is_blocked(self):
        script = '''
import importlib.abc
import json
from pathlib import Path
import sys
class BlockChatTS(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "gymts.integrations.chatts" or fullname.startswith("gymts.integrations.chatts."):
            raise ModuleNotFoundError("ChatTS is deliberately unavailable")
sys.meta_path.insert(0, BlockChatTS())
from gymts import GymTS
with GymTS(sys.argv[1]) as gym:
    assert any(item["name"] == "chatts" for item in gym.available_integrations())
    assert not any(name.startswith("gymts.integrations.chatts") for name in sys.modules)
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
                                     str(BASE / "examples" / "forecast_experiment.json")],
                                    cwd=BASE, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_text_adapter_import_does_not_load_native_candidate(self):
        script = '''
import importlib.abc
import sys
class BlockNativeCandidate(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "gymts.integrations.chatts.candidate":
            raise ModuleNotFoundError("Native ChatTS adapter is deliberately unavailable")
sys.meta_path.insert(0, BlockNativeCandidate())
from gymts.integrations.chatts.text_candidate import TextLLMHTTPCandidate
from gymts.http_candidate import FrozenJSONHTTPCandidate
assert TextLLMHTTPCandidate.__bases__ == (FrozenJSONHTTPCandidate,)
assert "gymts.integrations.chatts.candidate" not in sys.modules
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

    def test_installed_entry_point_discovery_does_not_load_until_selected(self):
        calls = []

        def register(registries, schemas):
            calls.append("register")
            schemas.register("example.external/1", {"type": "number"})

        def load():
            calls.append("load")
            return register

        entry = SimpleNamespace(name="external-example", value="example_plugin:register",
                                dist=SimpleNamespace(name="example-plugin"), load=load)
        # This also exercises Python 3.9's mapping-style metadata response.
        with patch("gymts.integrations.entry_points", return_value={"gymts.integrations": [entry]}):
            catalog = available_integrations()
            self.assertEqual([], calls)
            self.assertEqual("example-plugin", next(item for item in catalog
                             if item["name"] == "external-example")["distribution"])
            catalog[0]["name"] = "caller-mutated"
            self.assertNotIn("caller-mutated", [item["name"] for item in available_integrations()])
            with tempfile.TemporaryDirectory() as root, GymTS(root, integrations=("external-example",)) as gym:
                gym.schemas.validate("example.external/1", 3)
                gym.enable_integration("external-example")
            self.assertEqual(["load", "register"], calls)

    def test_duplicate_entry_points_and_unknown_names_are_rejected(self):
        entry = SimpleNamespace(name="chatts", value="other:register", load=lambda: None)
        with patch("gymts.integrations.entry_points", return_value={"gymts.integrations": [entry]}):
            info = next(item for item in available_integrations() if item["name"] == "chatts")
            self.assertEqual("conflict", info["status"])
            self.assertEqual(2, len(info["providers"]))
            with tempfile.TemporaryDirectory() as root, GymTS(root) as gym:
                with self.assertRaises(GymTSError) as caught:
                    gym.enable_integration("chatts")
                self.assertEqual("conflict", caught.exception.code)
        with tempfile.TemporaryDirectory() as root, GymTS(root) as gym:
            for name in ("missing-integration", "", None):
                with self.subTest(name=name), self.assertRaises(GymTSError):
                    gym.enable_integration(name)
            self.assertEqual((), gym.enabled_integrations)

    def test_unselected_broken_entry_point_does_not_block_other_integrations(self):
        def unavailable():
            raise ModuleNotFoundError("Missing optional distribution")

        entry = SimpleNamespace(name="unavailable-example", value="missing:register",
                                dist=None, load=unavailable)
        with patch("gymts.integrations.entry_points", return_value={"gymts.integrations": [entry]}):
            self.assertIn("unavailable-example", [item["name"] for item in available_integrations()])
            with tempfile.TemporaryDirectory() as root, GymTS(root, integrations=("chatts",)) as gym:
                with self.assertRaises(GymTSError) as caught:
                    gym.enable_integration("unavailable-example")
                self.assertEqual("unsupported_capability", caught.exception.code)
                self.assertEqual(("chatts",), gym.enabled_integrations)

    def test_another_names_metadata_conflict_does_not_block_chatts(self):
        entries = [SimpleNamespace(name="unrelated", value=value, dist=None, load=lambda: None)
                   for value in ("first:register", "second:register")]
        with patch("gymts.integrations.entry_points", return_value={"gymts.integrations": entries}):
            with tempfile.TemporaryDirectory() as root, GymTS(root, integrations=("chatts",)) as gym:
                self.assertEqual(("chatts",), gym.enabled_integrations)
                with self.assertRaises(GymTSError) as caught:
                    gym.enable_integration("unrelated")
                self.assertEqual("conflict", caught.exception.code)

    def test_failed_registration_rolls_back_all_roles_and_can_retry(self):
        calls = []

        class CallableFactory:
            def __call__(self, spec):
                return None

        with tempfile.TemporaryDirectory() as root, GymTS(root) as gym:
            factory = CallableFactory()
            manifest = gym.registries.candidates.resolve("last-value", "1.0.0")
            manifest["component_ref"]["name"] = "callable-factory-example"
            gym.registries.candidates.register(manifest, factory)
            kinds = ("environments", "tasks", "candidates", "scorers")
            originals = {kind: dict(getattr(gym.registries, kind)._entries) for kind in kinds}
            definitions = copy.deepcopy(gym.schemas._schemas)

            def register(registries, schemas):
                calls.append("register")
                schemas.register("example.transaction/1", {"type": "number"})
                for kind in kinds:
                    registry = getattr(registries, kind)
                    definition, component_factory = next(iter(originals[kind].values()))
                    definition = copy.deepcopy(definition)
                    definition["component_ref"]["name"] = "example-transaction-" + kind
                    registry.register(definition, component_factory)
                if len(calls) == 1:
                    raise GymTSError("invalid_config", "PRIVATE_PLUGIN_DETAIL_WITH_SECRET")

            entry = SimpleNamespace(name="transaction-example", value="example:register",
                                    dist=None, load=lambda: register)
            with patch("gymts.integrations.entry_points", return_value={"gymts.integrations": [entry]}):
                with self.assertRaises(GymTSError) as caught:
                    gym.enable_integration("transaction-example")
                self.assertNotIn("PRIVATE_PLUGIN_DETAIL", json.dumps(caught.exception.info))
                self.assertEqual((), gym.enabled_integrations)
                self.assertEqual(definitions, gym.schemas._schemas)
                for kind in kinds:
                    current = getattr(gym.registries, kind)._entries
                    self.assertEqual(originals[kind], current)
                    for key, (_, prior_factory) in originals[kind].items():
                        self.assertIs(prior_factory, current[key][1])
                spec = json.loads((BASE / "examples" / "forecast_experiment.json").read_text())
                self.assertEqual("succeeded", gym.run(spec)["status"])
                gym.enable_integration("transaction-example")
                self.assertEqual(("transaction-example",), gym.enabled_integrations)
                gym.schemas.validate("example.transaction/1", 4)
                for kind in kinds:
                    self.assertIn(("example-transaction-" + kind, "1.0.0"),
                                  getattr(gym.registries, kind)._entries)
            self.assertEqual(["register", "register"], calls)

    def test_invalid_integrations_collection_reports_contract_error(self):
        with tempfile.TemporaryDirectory() as root:
            for names in ("chatts", None, 1):
                with self.subTest(names=names), self.assertRaises(GymTSError) as caught:
                    GymTS(root, integrations=names)
                self.assertEqual("invalid_config", caught.exception.code)

    def test_common_http_transport_accepts_a_different_task_contract(self):
        class NumericCandidate(FrozenJSONHTTPCandidate):
            DEFAULTS = dict(FrozenJSONHTTPCandidate.DEFAULTS, dialect="example.numeric/v1")
            DIALECTS = ("example.numeric/v1",)
            TASK_PROTOCOL_REF = "example.task/numeric/1"
            OUTPUT_SCHEMA_REF = "example.output/1"

            def _load_input(self, task_input):
                return copy.deepcopy(task_input["payload"]["value"])

            def _wire(self, model_input):
                return {"model": self.model, "numeric_value": model_input}

        class Response:
            status = 200

            def read(self, size):
                return b'{"model":"numeric","choices":[{"message":{"content":"42"}}]}'[:size]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

        class Opener:
            def open(self, request, timeout):
                self.sent = json.loads(request.data)
                return Response()

        with tempfile.TemporaryDirectory() as root:
            candidate = NumericCandidate({"params": {"base_url": "http://localhost:12345",
                                          "model": "numeric", "model_revision": "fixed"}})
            candidate.prepare({"resources": ArtifactStore(Path(root)),
                               "learning": {"prepare": "load_only", "online": "frozen"}}, None)
            candidate.opener = Opener()
            result = candidate.infer({"input_id": "numeric-1", "task_protocol_ref": candidate.TASK_PROTOCOL_REF,
                                      "payload": {"storage": "inline", "value": 42}})
            self.assertEqual({"model": "numeric", "numeric_value": 42}, candidate.opener.sent)
            self.assertEqual(candidate.TASK_PROTOCOL_REF, result["task_protocol_ref"])
            self.assertEqual(candidate.OUTPUT_SCHEMA_REF, result["payload"]["schema_ref"])
            self.assertEqual("42", result["payload"]["value"]["raw_text"])
            candidate.finish()


if __name__ == "__main__":
    unittest.main()
