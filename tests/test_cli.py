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

    def test_registered_source_run_capture_and_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            options = ["--store", str(root / "runs"), "--data-home", str(root / "data"),
                       "--cache-home", str(root / "cache")]
            definition = {"protocol_version": "gymts.data-source/1", "source_id": "test/counter",
                "config": "default", "revision": None, "kind": "simulation",
                "provider_ref": {"name": "counter-transition", "version": "1.0.0", "origin_ref": None},
                "configuration": {"max_steps": 3}, "recipe": None,
                "reproducibility": {"mode": "seeded", "seed": 7},
                "usage_policy": {"allowed_uses": ["runtime", "evaluation"], "training_allowed": False},
                "parent_datasets": [], "card_ref": None}
            source_file = root / "source.json"
            source_file.write_text(json.dumps(definition))
            code, output, error = self.call(options + ["sources", "register", str(source_file), "--alias", "v1"])
            self.assertEqual(0, code, error)
            source = json.loads(output)
            code, output, error = self.call(options + ["sources", "list"])
            self.assertEqual(0, code, error)
            self.assertEqual(source["revision"], json.loads(output)["sources"][0]["revision"])
            capture_args = ["--source", source["source_id"], "--source-revision", "v1", "--dataset-id", "test/episode"]
            code, output, error = self.call(options + ["run-data", str(ROOT / "examples/counter_experiment.json")] + capture_args)
            self.assertEqual(0, code, error)
            result = json.loads(output)
            self.assertEqual("succeeded", result["run"]["status"])
            dataset = result["dataset"]
            self.assertEqual("simulation", dataset["kind"])
            self.assertEqual(source["revision"], dataset["origin"]["source_ref"]["revision"])
            self.assertGreater(dataset["splits"]["recorded"]["row_count"], 0)
            code, output, error = self.call(options + ["datasets", "capture", result["run"]["run_id"]] + capture_args)
            self.assertEqual(0, code, error)
            self.assertEqual(dataset["revision"], json.loads(output)["revision"])
            # The catalog is shared independently of the experiment root.
            options[1] = str(root / "new-runs")
            code, output, error = self.call(options + ["datasets", "info", "test/episode",
                "--revision", dataset["revision"], "--split", "recorded"])
            self.assertEqual(0, code, error)
            self.assertEqual(dataset["splits"]["recorded"]["row_count"], json.loads(output)["row_count"])

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
