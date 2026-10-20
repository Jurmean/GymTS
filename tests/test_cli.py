import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gymts.cli import main

ROOT = Path(__file__).resolve().parents[1]


class CommandLineTests(unittest.TestCase):
    def call(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_run_and_inspect_after_reopening_store(self):
        with tempfile.TemporaryDirectory() as root:
            code, output, error = self.call(["--store", root, "run", str(ROOT / "examples/counter_experiment.json")])
            self.assertEqual(code, 0, error)
            result = json.loads(output)
            self.assertEqual(result["summary"]["counts"]["operations"], 3)
            code, output, error = self.call(["--store", root, "inspect", result["run_id"]])
            self.assertEqual(code, 0, error)
            reopened = json.loads(output)
            self.assertEqual(reopened["result"], result)
            self.assertNotIn("events", reopened)

    def test_invalid_config_is_not_a_success_exit(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "invalid.json"
            spec = json.loads((ROOT / "examples/forecast_experiment.json").read_text())
            spec["execution"]["limits"]["max_input_typo"] = 1
            path.write_text(json.dumps(spec))
            code, output, _ = self.call(["--store", root, "validate", str(path)])
            self.assertEqual(code, 2)
            self.assertFalse(json.loads(output)["valid"])
            code, _, error = self.call(["--store", root, "run", str(path)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(error)["error"]["code"], "schema_mismatch")

    def test_evaluation_without_labels_is_completed_but_insufficient(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.json"
            code, output, error = self.call(["--store", root, "evaluate",
                str(ROOT / "examples/forecast_evaluation.json"), "--output", str(path)])
            self.assertEqual(code, 0, error)
            report = json.loads(output)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["verdict"], "insufficient_evidence")
            self.assertEqual(json.loads(path.read_text()), report)
            self.assertEqual(report["coverage"]["expected_units"], 2)

    def test_optional_integration_is_explicit_in_plugin_listing(self):
        def register(registries, schemas):
            manifest = registries.candidates.resolve("last-value", "1.0.0")
            manifest["component_ref"]["name"] = "external-cli-example"
            registries.candidates.register(manifest, lambda spec: None)

        entry = SimpleNamespace(name="external-cli", value="example:register", dist=None,
                                load=lambda: register)
        with patch("gymts.integrations.entry_points", return_value={"gymts.integrations": [entry]}), \
                tempfile.TemporaryDirectory() as root:
            code, output, error = self.call(["--store", root, "plugins"])
            self.assertEqual(0, code, error)
            names = {item["component_ref"]["name"] for item in json.loads(output)["candidates"]}
            self.assertNotIn("external-cli-example", names)
            code, output, error = self.call(["--store", root, "--integration", "external-cli", "plugins"])
            self.assertEqual(0, code, error)
            names = {item["component_ref"]["name"] for item in json.loads(output)["candidates"]}
            self.assertIn("external-cli-example", names)

    def test_unknown_integration_returns_a_structured_error(self):
        with tempfile.TemporaryDirectory() as root:
            code, output, error = self.call(["--store", root, "--integration", "unknown-integration", "plugins"])
            self.assertEqual(2, code)
            self.assertEqual("", output)
            self.assertEqual("unsupported_capability", json.loads(error)["error"]["code"])


if __name__ == "__main__":
    unittest.main()
