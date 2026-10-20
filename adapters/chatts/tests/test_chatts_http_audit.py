"""Safety regressions for the credential-free, read-only saved-run audit."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_chatts_http_experiment.py"
SPEC = importlib.util.spec_from_file_location("chatts_http_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class SavedRequestAuditTests(unittest.TestCase):
    def fixture(self):
        public = {"messages": [{"role": "user", "content": "Return JSON. Series X: <ts><ts/>"}],
                  "timeseries": [[-0.125, 1.23456789, 4.0]], "series_names": ["Series X"],
                  "output_schema": {"type": "object"}, "context": {}}
        request = {"native_timeseries": copy.deepcopy(public["timeseries"]),
                   "series_names": public["series_names"],
                   "wire_payload": {"messages": audit.project_text_messages(public)}}
        evidence = {"input_representation": "named_numeric_json/v1", "weights_pinned": False}
        return public, request, evidence

    def test_original_values_and_names_pass(self):
        public, request, evidence = self.fixture()
        self.assertTrue(all(audit.request_checks(public, request, evidence).values()))

    def test_rounding_on_wire_cannot_be_hidden_by_saved_native_arrays(self):
        public, request, evidence = self.fixture()
        request["wire_payload"]["messages"][0]["content"] = request["wire_payload"]["messages"][0]["content"].replace("1.23456789", "1.23")
        checks = audit.request_checks(public, request, evidence)
        self.assertTrue(checks["saved_native_arrays_exact"])
        self.assertFalse(checks["wire_numeric_arrays_and_names_exact"])
        self.assertFalse(checks["wire_messages_exact_public_projection"])

    def test_private_labels_added_to_wire_fail(self):
        public, request, evidence = self.fixture()
        request["wire_payload"]["private_context"] = {"expected_output": {"answer": "label"}}
        self.assertFalse(audit.request_checks(public, request, evidence)["no_private_structured_keys"])
        public["expected_output"] = {"answer": "label"}
        self.assertFalse(audit.request_checks(public, request, evidence)["public_input_whitelist"])

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for value in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.subTest(value=value), self.assertRaises(audit.AuditError):
                audit.decode(value)

    def test_cas_tampering_is_rejected_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = audit.canonical({"value": 1})
            revision = audit.sha(original)
            metadata = {"media_type": "application/json", "schema_ref": "test/1"}
            identity = audit.sha(audit.canonical({"content_hash": revision, "metadata": metadata}))
            ref = {"artifact_id": identity, "revision": revision, "content_hash": revision,
                   "size_bytes": len(original), "media_type": "application/json", "schema_ref": "test/1"}
            manifest = root / "refs" / identity / (revision + ".json")
            blob = root / "blobs" / revision[:2] / revision
            manifest.parent.mkdir(parents=True)
            blob.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"reference": ref, "metadata": metadata}))
            tampered = audit.canonical({"value": 2})
            blob.write_bytes(tampered)
            with self.assertRaisesRegex(audit.AuditError, "artifact_content_digest_mismatch"):
                audit.ReadOnlyCAS(root).read(ref)
            self.assertEqual(blob.read_bytes(), tampered)


if __name__ == "__main__":
    unittest.main()
