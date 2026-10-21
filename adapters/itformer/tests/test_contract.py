"""Lightweight contracts plus optional native-data CPU tests; no native inference."""
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from gymts import GymTS, GymTSError
from gymts.contracts import utc_now
from gymts.plugin_support import component, payload
from gymts_itformer.contracts import ALIGNMENT, INPUT, OUTPUT, PROTOCOL, PARSER_REF
from gymts_itformer.data import flatten_questions, prepare_view, select_indices
from gymts_itformer.runtime import safetensor_headers
from gymts_itformer.projection import RangeFile
from gymts_itformer.scoring import ReferenceScorer, lexical_f1, parse_options
from gymts_itformer.workflow import _installed_core, build_evaluation, freeze_core, score_spec, verify_frozen_core

native_data_cpu = unittest.skipUnless(
    all(importlib.util.find_spec(name) is not None for name in ("h5py", "numpy")),
    "native-data CPU group requires optional gymts-itformer[data] (h5py and numpy)")


class TestCandidate:
    """Only checks contracts; it does not represent an ITFormer model."""
    calls = 0

    def __init__(self, spec):
        pass

    def prepare(self, context, training):
        return {"model_revision": "test-only", "state_refs": [], "training_provenance_ref": None}

    def infer(self, task_input):
        type(self).calls += 1
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
            "model_revision": "test-only", "payload": payload(OUTPUT, {"raw_text": "a", "evidence": {"test_only": True}})}

    def update(self, feedback):
        raise AssertionError("test update forbidden")

    def finish(self):
        return []


def register_test_candidate(gym):
    gym.registries.candidates.register({"component_ref": component("itformer-test-only"),
        "protocol_versions": ["gymts.candidate/1", PROTOCOL], "params_schema_ref": "gymts.itformer/empty/1", "origin_ref": None,
        "implementation_ref": component("TestCandidate"), "component_refs": [], "supported_task_protocols": [PROTOCOL],
        "input_schema_refs": [INPUT], "output_schema_refs": [OUTPUT], "supports_fit": False,
        "fit_requires_targets": False, "supports_update": False, "model_revision_mode": "fixed", "capture_profiles": []}, TestCandidate)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gymts-itformer-test-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def installed_wheel_fixture(self, *, modified=None, missing=None, version=None):
        """Archive actual installed core bytes; this fixture never fakes a Run/model."""
        distribution = importlib.metadata.distribution("gymts")
        import gymts
        root = Path(gymts.__file__).resolve().parent.parent
        target = self.root / "gymts-installed-fixture.whl"
        with zipfile.ZipFile(target, "w") as archive:
            for path in (root / "gymts").rglob("*"):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                    continue
                name = str(path.relative_to(root))
                if name != missing:
                    archive.writestr(name, path.read_bytes() + (b"\n# changed fixture\n" if name == modified else b""))
            metadata = distribution.read_text("METADATA")
            if version:
                metadata = metadata.replace("Version: " + distribution.version + "\n", "Version: " + version + "\n")
            archive.writestr("gymts-" + distribution.version + ".dist-info/METADATA", metadata)
        return target

    def test_installed_core_accepts_supported_stable_series(self):
        actual = importlib.metadata.distribution("gymts")
        for version in ("0.5.1", "0.5.12", "0.6.0", "0.6.12"):
            with self.subTest(version=version):
                distribution = Mock(wraps=actual)
                distribution.version = version
                with patch("gymts_itformer.workflow.importlib.metadata.distribution", return_value=distribution), \
                        patch("gymts.__version__", version):
                    self.assertEqual(_installed_core()[0], version)

    def test_installed_core_rejects_unsupported_unstable_or_mismatched_versions(self):
        actual = importlib.metadata.distribution("gymts")
        for version in ("0.4.9", "0.7.0", "1.0.0", "0.6", "0.6.00", "0.6.0rc1", "0.6.0.post1", "0.5.1+local"):
            with self.subTest(version=version):
                distribution = Mock(wraps=actual)
                distribution.version = version
                with patch("gymts_itformer.workflow.importlib.metadata.distribution", return_value=distribution), \
                        patch("gymts.__version__", version):
                    with self.assertRaisesRegex(ValueError, "matching installed stable"):
                        _installed_core()
        with patch("gymts.__version__", actual.version + ".different"):
            with self.assertRaisesRegex(ValueError, "matching installed stable"):
                _installed_core()

    def test_freeze_matches_complete_actual_installed_core_without_local_paths(self):
        wheel = self.installed_wheel_fixture()
        expected_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as archive:
            expected_files = {name: hashlib.sha256(archive.read(name)).hexdigest()
                for name in archive.namelist() if name.startswith("gymts/") and not name.endswith("/")}
        identity = freeze_core(wheel, expected_wheel_sha256=expected_sha)
        self.assertEqual(identity["wheel_sha256"], expected_sha)
        self.assertEqual(identity["wheel_filename"], wheel.name)
        self.assertNotIn(str(self.root), json.dumps(identity))
        self.assertNotIn("git_commit", identity)
        self.assertEqual(identity["installed_files"], expected_files)
        path = self.root / "core-identity.json"
        path.write_text(json.dumps(identity))
        self.assertEqual(verify_frozen_core(path)["verified_files"], len(expected_files))

    def test_freeze_rejects_wrong_independently_expected_wheel_hash(self):
        wheel = self.installed_wheel_fixture()
        with self.assertRaisesRegex(ValueError, "expected hash"):
            freeze_core(wheel, expected_wheel_sha256="0" * 64)

    def test_freeze_rejects_modified_actual_core_payload(self):
        with self.assertRaisesRegex(ValueError, "Installed core bytes differ"):
            freeze_core(self.installed_wheel_fixture(modified="gymts/__init__.py"))

    def test_freeze_rejects_missing_payload_or_wrong_version(self):
        with self.assertRaisesRegex(ValueError, "membership"):
            freeze_core(self.installed_wheel_fixture(missing="gymts/py.typed"))
        with self.assertRaisesRegex(ValueError, "name/version"):
            freeze_core(self.installed_wheel_fixture(version="9.0.0"))

    def test_verify_rejects_modified_identity_hash_or_missing_member(self):
        identity = freeze_core(self.installed_wheel_fixture())
        path = self.root / "core-identity.json"
        changed = copy.deepcopy(identity)
        changed["installed_files"]["gymts/__init__.py"] = "0" * 64
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "Installed frozen core differs"):
            verify_frozen_core(path)
        changed = copy.deepcopy(identity)
        changed["installed_files"].pop("gymts/py.typed")
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "membership"):
            verify_frozen_core(path)

    def qa_fixture(self):
        qa = self.root / "qa.jsonl"
        rows = []
        for native_id in ("1", ["1"] * 10):
            conversations = []
            for stage in range(1, 5):
                conversations.extend([{"stage": str(stage), "attribute": "test", "value": "Read <ts> signal " + str(stage)},
                    {"value": "a" if stage in (2, 3) else "test-only private answer"}])
            rows.append({"id": native_id, "conversations": conversations})
        qa.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        return qa

    def fixture(self):
        """Real HDF5 data fixture, used only by the optional native-data CPU group."""
        import h5py
        import numpy as np
        h5 = self.root / "signals.h5"
        with h5py.File(h5, "w") as stream:
            stream.create_dataset("seq_data", data=np.arange(2 * 600 * 33, dtype="float32").reshape(2, 600, 33))
        qa = self.qa_fixture()
        return h5, qa

    def public_fixture(self):
        """Explicit JSON contract fixture; never an official asset or model result."""
        samples, targets = [], []
        revision = "explicit-test-only-public-view/1"
        for stage in range(1, 5):
            token = hashlib.sha256(("explicit-test-stage-" + str(stage)).encode()).hexdigest()
            samples.append({"sample_id": token, "source_line": 0, "qa_offset": stage - 1,
                "flattened_index": stage - 1, "signal_ids": ["explicit-test-only-signal"],
                "stage": stage, "form": "explicit-test-only", "question": "Read <ts> test fixture " + str(stage),
                "signal": [[float(i + j) for j in range(33)] for i in range(60)],
                "signal_shape": [60, 33], "projection_ref": "itformer-native-h5-selection/1"})
            targets.append({"sample_id": token, "answer": "a" if stage in (2, 3) else "test-only private answer",
                "stage": stage, "reference_status": "known", "allowed_uses": ["evaluation"]})
        view = self.root / "view"
        view.mkdir()
        (view / "public.json").write_text(json.dumps({"dataset_revision": revision, "samples": samples}))
        (view / "private-targets.json").write_text(json.dumps({"dataset_revision": revision, "targets": targets}))

    def test_flatten_retains_same_signal_questions(self):
        qa = self.qa_fixture()
        rows = flatten_questions(qa)
        self.assertEqual(len(rows), 8)
        self.assertEqual([row["flattened_index"] for row in rows], list(range(8)))
        self.assertEqual(rows[3]["source_line"], 0)
        self.assertEqual(rows[3]["qa_offset"], 3)
        self.assertEqual(select_indices(rows, 1), [0, 1, 2, 3])

    @native_data_cpu
    def test_native_data_prepare_separates_gold_and_preserves_all_channels(self):
        h5, qa = self.fixture()
        prepare_view(h5, qa, self.root / "view")
        public = json.loads((self.root / "view/public.json").read_text())
        private = json.loads((self.root / "view/private-targets.json").read_text())
        self.assertEqual(len(public["samples"]), 4)
        self.assertNotIn("test-only private answer", json.dumps(public))
        self.assertEqual(public["samples"][0]["signal_shape"], [600, 33])
        self.assertEqual(private["targets"][0]["allowed_uses"], ["evaluation"])
        self.assertEqual((self.root / "view/private-targets.json").stat().st_mode & 0o777, 0o600)

    @native_data_cpu
    def test_native_data_list_projection_and_distinct_qa_identity(self):
        h5, qa = self.fixture()
        prepare_view(h5, qa, self.root / "view", indices=[0, 4])
        rows = json.loads((self.root / "view/public.json").read_text())["samples"]
        self.assertNotEqual(rows[0]["sample_id"], rows[1]["sample_id"])
        self.assertEqual(rows[1]["signal_shape"], [600, 33])
        self.assertEqual(rows[1]["signal"][:60], rows[0]["signal"][:60])
        self.assertEqual(rows[1]["signal"][60:120], rows[0]["signal"][:60])

    @native_data_cpu
    def test_native_data_reject_nonfinite_signal_without_zero_fallback(self):
        import h5py
        h5, qa = self.fixture()
        with h5py.File(h5, "a") as stream:
            stream["seq_data"][0, 0, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            prepare_view(h5, qa, self.root / "view")

    @native_data_cpu
    def test_native_data_reject_duplicate_flattened_selection(self):
        h5, qa = self.fixture()
        with self.assertRaisesRegex(ValueError, "unique"):
            prepare_view(h5, qa, self.root / "view", indices=[0, 0])

    def test_reject_unpaired_conversation(self):
        qa = self.qa_fixture()
        qa.write_text(json.dumps({"id": "1", "conversations": [{"value": "question"}]}))
        with self.assertRaisesRegex(ValueError, "Unpaired"):
            flatten_questions(qa)

    def test_source_schema_refuses_answer_fields(self):
        self.public_fixture()
        sample = json.loads((self.root / "view/public.json").read_text())["samples"][0]
        with GymTS(self.root / "runs", integrations=("itformer",)) as gym:
            sample["answer"] = "must never reach candidate"
            with self.assertRaises(GymTSError):
                gym.schemas.validate(INPUT, sample)

    def test_strict_choice_parser_rejects_ambiguous_prose(self):
        self.assertEqual(parse_options("A), C)"), ["a", "c"])
        self.assertEqual(parse_options("A) bearing issue"), ["a"])
        self.assertIsNone(parse_options("A) issue B) alternative"))
        self.assertIsNone(parse_options("maybe a"))

    def test_lexical_score_does_not_claim_semantics(self):
        self.assertEqual(lexical_f1("a a b", "a b b"), 2 / 3)
        self.assertEqual(lexical_f1("", "reference"), 0)

    def test_safetensor_header_rejects_missing_payload(self):
        header = json.dumps({"ts_encoder.weight": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]}}).encode()
        (self.root / "model.safetensors").write_bytes(struct.pack("<Q", len(header)) + header)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            safetensor_headers(self.root)

    def test_native_pickle_precedence_cannot_bypass_weight_identity(self):
        from gymts_itformer.runtime import preflight
        (self.root / "pytorch_model.bin").write_bytes(b"test-only forbidden pickle placeholder")
        with patch("gymts_itformer.runtime.validate_source", side_effect=AssertionError("must reject before any loading")):
            with self.assertRaisesRegex(ValueError, "override native safetensors"):
                preflight("/missing/source", self.root, "/missing/base")

    def test_safetensor_header_rejects_index_mismatch(self):
        header = json.dumps({"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
        (self.root / "model.safetensors").write_bytes(struct.pack("<Q", len(header)) + header + b"\0" * 4)
        (self.root / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"wrong": "model.safetensors"}}))
        with self.assertRaisesRegex(ValueError, "index"):
            safetensor_headers(self.root)

    def test_range_reader_checks_exact_server_range(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 206
        response.headers = {"Content-Range": "bytes 8-11/100"}
        response.read.return_value = b"abcd"
        response.geturl.return_value = "https://example.invalid/public"
        reader = RangeFile("https://example.invalid/public", 100)
        reader.seek(8)
        with patch("urllib.request.urlopen", return_value=response) as transport:
            self.assertEqual(reader.read(4), b"abcd")
            reader.seek(8)
            self.assertEqual(reader.read(4), b"abcd")
            self.assertEqual(transport.call_count, 1)
        self.assertEqual(reader.receipts[0]["start"], 8)
        self.assertEqual(reader.total, 4)

    def test_range_reader_refuses_full_response_and_budget_overflow(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {}
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "exact requested byte range"):
                RangeFile("https://example.invalid/public", 100).read(4)
        with self.assertRaisesRegex(ValueError, "budget"):
            RangeFile("https://example.invalid/public", 100, max_bytes=2).read(4)

    @native_data_cpu
    def test_native_data_projection_rejects_changed_membership(self):
        from gymts_itformer.data import file_identity
        h5, qa = self.fixture()
        projection = {"kind": "derived-selected-official-hdf5", "revision": "test-revision",
            "derived_asset": file_identity(h5), "qa_asset": file_identity(qa),
            "selected_flattened_indices": [7], "signals": []}
        with self.assertRaisesRegex(ValueError, "membership"):
            prepare_view(h5, qa, self.root / "view", revision="test-revision", projection=projection)

    def test_one_command_prepare_rejects_nonofficial_qa_before_network(self):
        from gymts_itformer.projection import prepare_official
        invalid = self.root / "not-official.jsonl"
        invalid.write_text('{"test-only":"not an official benchmark"}')
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            with self.assertRaisesRegex(ValueError, "official LFS identity"):
                prepare_official(self.root / "prepared", qa_path=invalid)

    def test_one_command_download_rejects_wrong_lfs_content(self):
        from gymts_itformer.projection import prepare_official
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"wrong public data"
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "LFS identity"):
                prepare_official(self.root / "prepared")
        self.assertFalse((self.root / "prepared/test_qa.jsonl").exists())

    def test_plan_does_not_open_native_paths(self):
        self.public_fixture()
        with GymTS(self.root / "runs", integrations=("itformer",)) as gym:
            spec = self.spec(gym)
            case = spec["cases"][0]
            experiment = {"protocol_version": "gymts.experiment/1", "name": spec["name"], "purpose": "acceptance",
                "scene": case["scene"], "candidate": spec["candidates"][0]["spec"], "execution": case["execution"],
                "recording": case["recording"], "extensions": {}}
            with patch("gymts_itformer.runtime.load_native", side_effect=AssertionError("native load forbidden")):
                gym.plan(experiment)

    def spec(self, gym):
        view = self.root / "view"
        return build_evaluation(gym, json.loads((view / "public.json").read_text()),
            json.loads((view / "private-targets.json").read_text()), {"source_path": "/missing/source",
                "checkpoint_path": "/missing/checkpoint", "base_model_path": "/missing/base", "device": "cpu", "max_new_tokens": 8})

    def test_sdk_evaluate_and_rescore_without_execution(self):
        self.public_fixture()
        TestCandidate.calls = 0
        with GymTS(self.root / "runs", integrations=("itformer",)) as gym:
            register_test_candidate(gym)
            spec = self.spec(gym)
            spec["cases"][0]["recording"]["model_calls"] = "none"
            spec["candidates"][0]["spec"].update(adapter="itformer-test-only", params={})
            report = gym.autobench.evaluate(spec)
            self.assertEqual(report["status"], "completed", report.get("errors"))
            self.assertEqual(report["verdict"], "pass", report.get("errors"))
            self.assertEqual(TestCandidate.calls, 4)
            metrics = {item["metric_id"]: item["result"] for item in report["metrics"] if item["level"] == "unit"}
            self.assertEqual(metrics["answer_exact_match"]["counts"]["eligible"], 4)
            self.assertEqual(metrics["answer_exact_match"]["value"], 0.5)
            with patch.object(gym.environment_ts, "run", side_effect=AssertionError("new run forbidden")):
                second = gym.autobench.score(score_spec(gym, spec, report))
            self.assertEqual(second["verdict"], "pass")
            self.assertEqual(TestCandidate.calls, 4)
            self.assertEqual([item["result"] for item in report["metrics"]], [item["result"] for item in second["metrics"]])

    def test_reject_private_membership_mismatch(self):
        self.public_fixture()
        public = json.loads((self.root / "view/public.json").read_text())
        private = json.loads((self.root / "view/private-targets.json").read_text())
        private["targets"].pop()
        with GymTS(self.root / "runs", integrations=("itformer",)) as gym:
            with self.assertRaisesRegex(ValueError, "align"):
                build_evaluation(gym, public, private, {})

    def test_partial_run_retains_all_planned_qa_in_denominator(self):
        self.public_fixture()
        original = TestCandidate.infer
        attempts = []
        def interrupted(candidate, task_input):
            attempts.append(task_input["input_id"])
            if len(attempts) > 1:
                raise RuntimeError("intentional test-only second-input failure")
            return original(candidate, task_input)
        with GymTS(self.root / "runs", integrations=("itformer",)) as gym:
            register_test_candidate(gym)
            spec = self.spec(gym)
            spec["cases"][0]["recording"]["model_calls"] = "none"
            spec["candidates"][0]["spec"].update(adapter="itformer-test-only", params={})
            with patch.object(TestCandidate, "infer", interrupted):
                report = gym.autobench.evaluate(spec)
            metrics = {item["metric_id"]: item["result"] for item in report["metrics"] if item["level"] == "unit"}
            self.assertEqual(metrics["answer_exact_match"]["counts"],
                {"eligible": 4, "scored": 1, "missing": 3, "invalid": 0, "excluded": 0})
            self.assertEqual(report["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()
