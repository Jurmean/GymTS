"""Boundary and integrity tests using explicitly constructed source fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, canonical_json
from gymts_chatts.data import TASKS, export_sft, generate_profiles, import_profiles


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _fixture(path, *, tasks=("pattern.trend_direction",), bundles=5):
    """Small format fixture; these rows are not claimed as generated ChatTS data."""
    path.mkdir(parents=True)
    instances, artifacts, metadata = [], [], []
    classical = tasks[0] not in list(TASKS)[:3]
    for task_id in tasks:
        definition = TASKS[task_id]
        for bundle in range(bundles):
            for view in range(2):
                sample_id = f"fixture-{task_id}-SECRET_LABEL-b{bundle}::v{view}"
                if task_id == "pattern.trend_direction":
                    expected = {"trend_direction": "increasing"}
                elif task_id == "anomaly.point_indices":
                    expected = {"indices": [3]}
                elif task_id == "forecast.numeric":
                    expected = {"forecast": [4.0, 5.0]}
                elif task_id == "relation.lagged_dependence":
                    expected = {"direction": "x_to_y", "lag": 2}
                else:
                    field = definition["label_field"]
                    expected = {field: definition["labels"][0]}
                # Preserve serialized source order even when it differs from Task order.
                keys = sorted(definition["modality_keys"])
                modalities = {key: {"type": "timeseries", "content": [float(i + index) for i in range(8)]}
                              for index, key in enumerate(keys)}
                names = {"query": "Query", "candidate_a": "Candidate A", "candidate_b": "Candidate B",
                         "candidate_c": "Candidate C", "candidate_d": "Candidate D",
                         "series_x": "Series X", "series_y": "Series Y", "series": "Series 1"}
                series = [{"series_id": "series_0" if key == "series" else key,
                           "name": names[key], "values": modality["content"],
                           "properties": {"private_secret": "DO_NOT_SEND"}}
                          for key, modality in modalities.items()]
                metrics = []
                field = definition.get("label_field", "forecast" if task_id == "forecast.numeric" else "indices")
                for index, metric_id in enumerate(definition["metrics"]):
                    parameters = {} if metric_id == "metric.exact_match" else {"prediction_path": "/" + field, "expected_path": "/" + field}
                    if metric_id == "metric.anomaly.event_f1":
                        parameters["tolerance"] = 0
                    metrics.append({"id": metric_id, "version": "0.1.0", "parameters": parameters,
                                    "role": "primary" if index == 0 else "secondary", "aggregation": "point"})
                parser = {"id": "parser.structured_json", "version": "0.1.0", "parameters": {
                    "mode": "strict", "root_type": "object", "schema": copy.deepcopy(definition["output_schema"])}}
                instances.append({"schema": "chatts-bench/evaluation-instance/v0.1", "instance_id": sample_id + "::primary",
                    "task": {"task_id": task_id, "version": definition["version"]},
                    "input": {"modalities": modalities}, "context": {}, "instruction": {"messages": [
                        {"role": "system", "content": "Return the requested JSON answer."},
                        {"role": "user", "content": "Forecast the next 2 values of the attached time series." if task_id == "forecast.numeric" else "Analyze the attached series."}]},
                    "expected_output": expected, "evaluation": {"parser": parser, "metrics": metrics},
                    "metadata": {"private_secret": "DO_NOT_SEND"}})
                gold = {"answer": expected}
                if task_id == "pattern.trend_direction":
                    gold = {"series": {"series_0": expected}}
                elif task_id == "anomaly.point_indices":
                    gold = {"series": {"series_0": {"spike_indices": expected["indices"]}}}
                elif task_id == "forecast.numeric":
                    gold = {"future": {"series_0": expected["forecast"]}}
                artifacts.append({"artifact_id": sample_id, "series": series, "ground_truth": gold,
                                  "validation": {"valid": True}})
                metadata.append({"sample_id": sample_id, "bundle_id": f"fixture-{task_id}-b{bundle}",
                    "view_id": f"SECRET_LABEL-{view}", "task_id": task_id, "task_version": definition["version"],
                    "task_oracle": {"passed": True, "private_secret": "DO_NOT_SEND"}})
    manifest = {"schema": "chatts-bench/classical-concepts-profile-artifact/v0.1" if classical else "chatts-bench/native-task-profile-artifact/v0.2",
        "profile_id": "fixture.classical" if classical else "fixture.native", "formal_benchmark": False,
        "tasks": {t: TASKS[t]["version"] for t in (list(TASKS)[3:] if classical else list(TASKS)[:3])},
        "row_count": len(instances), "files": {}}
    for filename, rows in (("instances.jsonl", instances), ("generation.jsonl", artifacts), ("metadata.jsonl", metadata)):
        payload = b"".join(canonical_json(row) + b"\n" for row in rows)
        (path / filename).write_bytes(payload)
        manifest["files"][filename] = {"sha256": _sha(payload), "size_bytes": len(payload)}
    (path / "manifest.json").write_bytes(canonical_json(manifest))
    return path


def _mutate(path, filename, change):
    manifest = json.loads((path / "manifest.json").read_bytes())
    rows = [json.loads(line) for line in (path / filename).read_bytes().splitlines()]
    change(rows)
    payload = b"".join(canonical_json(row) + b"\n" for row in rows)
    (path / filename).write_bytes(payload)
    manifest["files"][filename] = {"sha256": _sha(payload), "size_bytes": len(payload)}
    (path / "manifest.json").write_bytes(canonical_json(manifest))


class ChatTSDataContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.gym = GymTS(self.root / "gym", integrations=("chatts",))

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def assertRejected(self, callback):
        with self.assertRaises(GymTSError):
            callback()

    def test_public_snapshot_whitelist_and_private_gold_are_separate(self):
        profile = _fixture(self.root / "source")
        result = import_profiles(self.gym, [profile])
        snapshot = self.gym.artifacts.read_json(result["snapshot_ref"])
        self.assertEqual({"schema_version", "dataset_revision", "samples"}, set(snapshot))
        sample = snapshot["samples"][0]
        self.assertEqual({"sample_token", "task_id", "task_version", "model_input"}, set(sample))
        self.assertEqual({"messages", "timeseries", "series_names", "output_schema", "context"}, set(sample["model_input"]))
        encoded = json.dumps(snapshot)
        for secret in ("DO_NOT_SEND", "SECRET_LABEL", "source_instance_id", "expected_output", "private_ref", "provenance"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(64, len(sample["sample_token"]))
        private = self.gym.artifacts.read_json(result["private_ref"])
        self.assertEqual({"trend_direction": "increasing"}, private["samples"][0]["expected_output"])
        self.assertEqual(result["dataset_revision"], result["samples"][0]["alignment_key"]["dataset_revision"])

    def test_multiseries_order_and_names_match_source_values(self):
        profile = _fixture(self.root / "source", tasks=("similarity.shape_retrieval",))
        result = import_profiles(self.gym, [profile])
        model = self.gym.artifacts.read_json(result["snapshot_ref"])["samples"][0]["model_input"]
        self.assertEqual(["Candidate A", "Candidate B", "Candidate C", "Candidate D", "Query"], model["series_names"])
        self.assertEqual([0.0, 1.0, 2.0, 3.0, 4.0], [v[0] for v in model["timeseries"]])

    def test_forecast_horizon_comes_from_public_instruction(self):
        profile = _fixture(self.root / "source", tasks=("forecast.numeric",))
        result = import_profiles(self.gym, [profile])
        model = self.gym.artifacts.read_json(result["snapshot_ref"])["samples"][0]["model_input"]
        self.assertEqual({"horizon": 2}, model["context"])
        self.assertNotIn("future", model)
        _mutate(profile, "instances.jsonl", lambda rows: rows[0]["expected_output"]["forecast"].append(6.0))
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))

    def test_manifest_hash_duplicate_instance_and_unknown_task_rejected(self):
        profile = _fixture(self.root / "source")
        (profile / "instances.jsonl").write_bytes(b"tampered")
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))
        profile = _fixture(self.root / "duplicate")
        self.assertRejected(lambda: import_profiles(self.gym, [profile, profile]))
        profile = _fixture(self.root / "unknown")
        _mutate(profile, "instances.jsonl", lambda rows: rows[0]["task"].update(task_id="unknown.task"))
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))

    def test_invalid_gold_schema_and_schema_relaxation_rejected(self):
        profile = _fixture(self.root / "source")
        _mutate(profile, "instances.jsonl", lambda rows: rows[0]["expected_output"].update(trend_direction="secret"))
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))
        profile = _fixture(self.root / "schema")
        _mutate(profile, "instances.jsonl", lambda rows: rows[0]["evaluation"]["parser"]["parameters"]["schema"].update(additionalProperties=True))
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))

    def test_source_generation_oracle_and_values_must_agree(self):
        profile = _fixture(self.root / "source")
        _mutate(profile, "generation.jsonl", lambda rows: rows[0]["validation"].update(valid=False))
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))
        profile = _fixture(self.root / "values")
        _mutate(profile, "instances.jsonl", lambda rows: rows[0]["input"]["modalities"]["series"]["content"].__setitem__(0, 999))
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))

    def test_nonfinite_json_and_duplicate_json_key_rejected(self):
        for name, replacement in (("nan", b'{"bad":NaN}\n'), ("duplicate", b'{"bad":1,"bad":2}\n')):
            profile = _fixture(self.root / name)
            manifest = json.loads((profile / "manifest.json").read_bytes())
            (profile / "instances.jsonl").write_bytes(replacement)
            manifest["files"]["instances.jsonl"] = {"sha256": _sha(replacement), "size_bytes": len(replacement)}
            (profile / "manifest.json").write_bytes(canonical_json(manifest))
            self.assertRejected(lambda: import_profiles(self.gym, [profile]))

    def test_nonwhitelisted_context_and_unsafe_manifest_path_rejected(self):
        profile = _fixture(self.root / "source")
        _mutate(profile, "instances.jsonl", lambda rows: rows[0]["context"].update(expected_output="DO_NOT_SEND"))
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))
        profile = _fixture(self.root / "path")
        manifest = json.loads((profile / "manifest.json").read_bytes())
        manifest["files"]["../outside"] = {"sha256": "x", "size_bytes": 0}
        (profile / "manifest.json").write_bytes(canonical_json(manifest))
        self.assertRejected(lambda: import_profiles(self.gym, [profile]))

    def test_sft_split_is_bundle_disjoint_reproducible_and_gold_marked(self):
        profile = _fixture(self.root / "source", bundles=10)
        imported = import_profiles(self.gym, [profile])
        first = export_sft(self.gym, imported, self.root / "sft-one", seed=17)
        second = export_sft(self.gym, imported, self.root / "sft-two", seed=17)
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(16, first["counts"]["train"])
        self.assertEqual(4, first["counts"]["eval"])
        self.assertFalse(set(first["splits"]["train"]["bundle_tokens"]) & set(first["splits"]["eval"]["bundle_tokens"]))
        self.assertFalse(set(first["train_sample_tokens"]) & set(first["eval_sample_tokens"]))
        rows = [json.loads(x) for x in (self.root / "sft-one/train.jsonl").read_text().splitlines()]
        self.assertTrue(all(r["answer_source"] == "synthetic_gold" for r in rows))
        self.assertTrue(all(isinstance(r["model_input"]["timeseries"][0], list) for r in rows))
        self.assertNotIn("SECRET_LABEL", json.dumps(rows[0]["model_input"]))
        self.assertEqual(first["files"]["train.jsonl"]["sha256"], _sha((self.root / "sft-one/train.jsonl").read_bytes()))
        self.assertRejected(lambda: export_sft(self.gym, imported, self.root / "sft-one"))

    def test_sft_uses_persisted_private_artifact_not_mutable_return_value(self):
        profile = _fixture(self.root / "source")
        imported = import_profiles(self.gym, [profile])
        imported["samples"][0]["expected_output"] = {"trend_direction": "wrong"}
        export_sft(self.gym, imported, self.root / "sft")
        rows = [json.loads(x) for x in (self.root / "sft/train.jsonl").read_text().splitlines()]
        self.assertTrue(all(r["answer"] == {"trend_direction": "increasing"} for r in rows))

    def test_generation_bridge_validates_outputs_and_preserves_source(self):
        repo = self.root / "repo"
        executable = repo / ".conda/task-system/bin/python"
        executable.parent.mkdir(parents=True)
        executable.write_text("fixture")
        identity = {"git_revision": "fixture", "worktree_dirty": True, "code_sha256": {}}
        def generate(command, **kwargs):
            self.assertEqual(str(repo.resolve()), kwargs["cwd"])
            self.assertEqual("1", kwargs["env"]["PYTHONDONTWRITEBYTECODE"])
            _fixture(Path(command[-1]))
            return subprocess_result()
        with patch("gymts_chatts.data._source_identity", return_value=identity), patch("gymts_chatts.data.subprocess.run", side_effect=generate):
            paths = generate_profiles(repo, self.root / "generated", profiles=("native",))
        self.assertEqual([(self.root / "generated/native").resolve()], paths)
        provenance = json.loads((self.root / "generated/source_provenance.json").read_text())
        self.assertEqual(identity, provenance["source"])
        self.assertRejected(lambda: generate_profiles(repo, self.root / "generated", profiles=("native",)))


def subprocess_result():
    class Result:
        returncode, stdout, stderr = 0, "generated fixture", ""
    return Result()


if __name__ == "__main__":
    unittest.main()
