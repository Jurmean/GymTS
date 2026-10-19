#!/usr/bin/env python3
"""Audit saved ChatTS/ordinary-LLM experiments without credentials or API calls.

Usage: python3 scripts/audit_chatts_http_experiment.py EXPERIMENT --output NEW.json

Only the selected experiment's summary, reports, immutable CAS, and read-only
SQLite RunResult columns are read. No GymTS runtime is instantiated, environment
variables are not inspected, and prompts/responses are not copied into output.
An evidence audit can pass even when a model's quality/coverage gate fails.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys


class AuditError(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise AuditError("duplicate_json_key")
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(AuditError("nonfinite_json")))


class ReadOnlyCAS:
    """Validate local ref metadata and bytes without constructing a write store."""
    def __init__(self, root):
        self.root, self.cache = Path(root).resolve(), {}

    def local(self, path, subdirectory):
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(self.root / subdirectory)
        except ValueError:
            raise AuditError("artifact_path_outside_store") from None
        return resolved

    def read(self, ref):
        identity, revision = ref.get("artifact_id"), ref.get("revision")
        if not all(isinstance(x, str) and re.fullmatch(r"[0-9a-f]{64}", x) for x in (identity, revision)):
            raise AuditError("invalid_local_artifact_identity")
        key = (identity, revision)
        if key in self.cache:
            saved_ref, value = self.cache[key]
            if canonical(saved_ref) != canonical(ref):
                raise AuditError("artifact_ref_relabelled")
            return value
        manifest = decode(self.local(self.root / "refs" / identity / (revision + ".json"), "refs").read_bytes())
        if canonical(manifest.get("reference", manifest)) != canonical(ref):
            raise AuditError("artifact_reference_mismatch")
        if "metadata" in manifest and sha(canonical({"content_hash": revision, "metadata": manifest["metadata"]})) != identity:
            raise AuditError("artifact_metadata_digest_mismatch")
        data = self.local(self.root / "blobs" / revision[:2] / revision, "blobs").read_bytes()
        if sha(data) != revision or ref.get("content_hash") != revision or len(data) != ref.get("size_bytes"):
            raise AuditError("artifact_content_digest_mismatch")
        value = decode(data)
        self.cache[key] = (ref, value)
        return value

    def payload(self, value):
        return value["value"] if value["storage"] == "inline" else self.read(value["artifact_ref"])


PRIVATE_KEYS = {"expected_output", "ground_truth", "private_ref", "source_private_ref",
                "source_instance_id", "source_metadata", "task_oracle", "bundle_id",
                "bundle_token", "view_id", "authorization", "api_key", "api_key_env",
                "credential_ref", "password", "secret", "training_targets"}


def private_keys(value):
    found = set()
    if isinstance(value, dict):
        found.update(key for key in value if key.lower() in PRIVATE_KEYS)
        for item in value.values():
            found.update(private_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(private_keys(item))
    return found


def numeric_json(names, arrays):
    return canonical({"representation": "named_numeric_json/v1",
                      "series": [{"name": name, "values": values}
                                 for name, values in zip(names, arrays)]}).decode("utf-8")


def project_text_messages(model_input):
    """Independent projection of the documented named_numeric_json/v1 format."""
    messages = decode(canonical(model_input["messages"]))
    indices = [i for i, message in enumerate(messages) if message["role"] == "user"]
    if not indices:
        raise AuditError("missing_user_message")
    index = indices[-1]
    text = messages[index]["content"]
    placeholder = "<ts><ts/>"
    count = sum(message["content"].count(placeholder) for message in messages)
    if count:
        if count != text.count(placeholder) or count != len(model_input["timeseries"]):
            raise AuditError("placeholder_projection_mismatch")
        chunks, parts = text.split(placeholder), []
        for i, chunk in enumerate(chunks[:-1]):
            parts.extend((chunk, numeric_json([model_input["series_names"][i]], [model_input["timeseries"][i]])))
        messages[index]["content"] = "".join(parts + [chunks[-1]])
    else:
        messages[index]["content"] = text + "\n\nTime series data (named_numeric_json/v1; original numerical values and order):\n" + numeric_json(
            model_input["series_names"], model_input["timeseries"])
    return messages


def extract_named_series(messages):
    """Read actual JSON from wire text; ignore schema objects in source prompts."""
    result = []
    decoder = json.JSONDecoder()
    for message in messages:
        content = message.get("content")
        if not isinstance(content, str):
            raise AuditError("text_wire_contains_nontext_content")
        position = 0
        while position < len(content):
            start = content.find("{", position)
            if start < 0:
                break
            try:
                value, end = decoder.raw_decode(content, start)
            except json.JSONDecodeError:
                position = start + 1
                continue
            if isinstance(value, dict) and value.get("representation") == "named_numeric_json/v1":
                result.extend(value["series"])
            position = end
    return result


def request_checks(model_input, request, evidence):
    wire = request["wire_payload"]
    names, arrays = model_input["series_names"], model_input["timeseries"]
    whitelist = {"messages", "timeseries", "series_names", "output_schema", "context"}
    checks = {
        "public_input_whitelist": set(model_input) == whitelist,
        "no_private_structured_keys": not private_keys(model_input) and not private_keys(wire),
        "saved_native_arrays_exact": canonical(request.get("native_timeseries")) == canonical(arrays),
        "saved_names_exact": request.get("series_names") == names,
        "wire_no_headers_or_credentials": not ({"headers", "authorization", "api_key", "api_key_env"} & set(wire)),
    }
    representation = evidence.get("input_representation", request.get("input_representation"))
    if representation == "named_numeric_json/v1":
        actual = extract_named_series(wire["messages"])
        expected = [{"name": name, "values": values} for name, values in zip(names, arrays)]
        checks.update(
            wire_numeric_arrays_and_names_exact=canonical(actual) == canonical(expected),
            wire_messages_exact_public_projection=canonical(wire["messages"]) == canonical(project_text_messages(model_input)),
            weights_not_claimed_pinned=evidence.get("weights_pinned") is False,
        )
    elif "timeseries" in wire:
        checks["wire_numeric_arrays_and_names_exact"] = canonical(wire["timeseries"]) == canonical(arrays)
        checks["wire_messages_exact_public_projection"] = wire["messages"] == model_input["messages"]
    else:
        # The audit intentionally fails closed for an unimplemented native
        # envelope projection instead of claiming that it verified the values.
        checks["supported_wire_projection"] = False
    return checks


def logical_units(cas, report):
    plan = cas.read(report["plan_ref"])
    units = {item["unit_id"]: item for item in plan["expected_units"]}
    manifest = cas.read(report["run_manifest_ref"])
    output = {}
    for entry in manifest["entries"]:
        unit = units[entry["unit_id"]]
        identity = (unit["candidate_id"], unit["evaluation_case_id"], unit["repetition"])
        if identity in output:
            raise AuditError("duplicate_logical_evaluation_unit")
        output[identity] = (unit, entry)
    if len(output) != len(units):
        raise AuditError("planned_unit_missing_from_manifest")
    return output


def audit_experiment(experiment):
    root = Path(experiment).resolve(strict=True)
    summary_path = root / "summary.json"
    summary_bytes = summary_path.read_bytes()
    summary = decode(summary_bytes)
    cas = ReadOnlyCAS(root / "records" / "artifacts")
    connection = sqlite3.connect((root / "records" / "records.sqlite3").as_uri() + "?mode=ro", uri=True)
    findings, warnings, tasks, all_runs = [], [], {}, []
    token_totals, response_models, fingerprints, finish_reasons = Counter(), Counter(), Counter(), Counter()

    def check(condition, code, task_id, run_id=None):
        if not condition:
            findings.append({"code": code, "task_id": task_id, "run_id": run_id})
        return bool(condition)

    try:
        for task_id in sorted(summary["tasks"]):
            if not re.fullmatch(r"[a-z][a-z0-9_.]*", task_id):
                raise AuditError("unsafe_task_identifier")
            stem = task_id.replace(".", "_")
            report_path = root / "reports" / (stem + ".json")
            before_path = root / "reports" / (stem + ".before_labels.json")
            report_bytes, before_bytes = report_path.read_bytes(), before_path.read_bytes()
            report, before = decode(report_bytes), decode(before_bytes)
            current, prior = logical_units(cas, report), logical_units(cas, before)
            check(set(current) == set(prior), "rescore_changed_planned_units", task_id)
            check(report["previous_evaluation_id"] == before["evaluation_id"], "rescore_parent_identity_mismatch", task_id)
            grouped = {}
            for identity, (unit, entry) in current.items():
                candidate = identity[0]
                group = grouped.setdefault(candidate, {"planned_units": 0, "run_statuses": Counter(),
                    "http_calls": 0, "usage": Counter(), "response_models": Counter(),
                    "system_fingerprints": Counter(), "finish_reasons": Counter(), "metrics": [],
                    "sealed_run_result_checks_passed": 0, "http_request_checks_passed": 0})
                group["planned_units"] += 1
                group["run_statuses"][entry["status"]] += 1
                run_id = entry["run_id"]
                old_entry = prior.get(identity, (None, {}))[1]
                unchanged = check(old_entry.get("run_id") == run_id, "rescore_changed_run_id", task_id, run_id)
                unchanged &= check(old_entry.get("run_result_ref") == entry["run_result_ref"], "rescore_changed_run_result_ref", task_id, run_id)
                if not run_id:
                    continue
                run_result = cas.read(entry["run_result_ref"])
                stored = connection.execute("SELECT result,result_ref,trace_ref FROM runs WHERE run_id=?", (run_id,)).fetchone()
                unchanged &= check(stored is not None and canonical(decode(stored[0])) == canonical(run_result), "current_sqlite_run_result_differs", task_id, run_id)
                unchanged &= check(stored is not None and decode(stored[1]) == entry["run_result_ref"] and decode(stored[2]) == run_result["trace_ref"], "current_sqlite_sealed_refs_differ", task_id, run_id)
                group["sealed_run_result_checks_passed"] += int(unchanged)
                trace = cas.read(run_result["trace_ref"])
                events = trace["events"]
                inputs, outputs = {}, {}
                for event in events:
                    if event["kind"] in ("input", "candidate_output"):
                        value = cas.payload(event["payload"])
                        (inputs if event["kind"] == "input" else outputs)[value["input_id"]] = value
                result_rows = cas.read(run_result["result_ref"])
                result_rows = result_rows.get("results", []) if isinstance(result_rows, dict) else result_rows
                item = {"task_id": task_id, "candidate_id": candidate, "run_id": run_id,
                    "evaluation_case_id": identity[1], "repetition": identity[2], "status": entry["status"],
                    "run_result_content_hash": entry["run_result_ref"]["content_hash"],
                    "trace_content_hash": run_result["trace_ref"]["content_hash"],
                    "run_result_unchanged_after_rescore": unchanged, "input_count": len(inputs),
                    "output_count": len(outputs), "result_statuses": dict(Counter(x["status"] for x in result_rows))}
                output_items = []
                for input_id, output in outputs.items():
                    raw = cas.payload(output["payload"])
                    evidence = raw.get("evidence", {})
                    captured = {"raw_text_sha256": sha(raw["raw_text"].encode("utf-8")),
                                "raw_text_chars": len(raw["raw_text"]), "kind": evidence.get("kind")}
                    matched_results = [result for result in result_rows if result["input_id"] == input_id]
                    check(len(matched_results) == 1, "candidate_output_result_link_count", task_id, run_id)
                    for result in matched_results:
                        result_payload = cas.payload(result["payload"])
                        check(result_payload.get("raw_text") == raw["raw_text"],
                              "task_result_did_not_preserve_raw_text", task_id, run_id)
                        if result["status"] == "invalid":
                            check(result_payload.get("parsed") is None and bool(result_payload.get("reason")),
                                  "invalid_result_missing_parser_failure_evidence", task_id, run_id)
                            captured["parser_failure_reason"] = result_payload.get("reason")
                    if evidence.get("kind") in ("text_llm_http", "chatts_http"):
                        check("request_ref" in evidence and "response_ref" in evidence,
                              "http_candidate_missing_saved_call_artifacts", task_id, run_id)
                    if "request_ref" in evidence and "response_ref" in evidence:
                        request, response = cas.read(evidence["request_ref"]), cas.read(evidence["response_ref"])
                        model_input = cas.payload(inputs[input_id]["payload"])
                        checks = request_checks(model_input, request, evidence)
                        for name, value in checks.items():
                            check(value, name, task_id, run_id)
                        body = response.get("body", {})
                        choice = (body.get("choices") or [{}])[0]
                        usage = body.get("usage") or {}
                        identity_values = {"response_model": body.get("model"),
                            "system_fingerprint": body.get("system_fingerprint"), "finish_reason": choice.get("finish_reason")}
                        check((choice.get("message") or {}).get("content") == raw["raw_text"],
                              "candidate_output_did_not_preserve_http_response", task_id, run_id)
                        check(evidence.get("response_model") == body.get("model")
                              and evidence.get("system_fingerprint") == body.get("system_fingerprint")
                              and evidence.get("finish_reason") == choice.get("finish_reason")
                              and evidence.get("usage") == usage,
                              "candidate_evidence_differs_from_http_response", task_id, run_id)
                        check(type(response.get("http_status")) is int and 200 <= response["http_status"] < 300,
                              "non_successful_http_response", task_id, run_id)
                        captured.update(identity_values, usage=usage, request_checks=checks,
                                        http_status=response.get("http_status"), request_content_hash=evidence["request_ref"]["content_hash"],
                                        response_content_hash=evidence["response_ref"]["content_hash"],
                                        revision_provenance=evidence.get("revision_provenance"),
                                        weights_pinned=evidence.get("weights_pinned"))
                        group["http_calls"] += 1
                        group["http_request_checks_passed"] += int(all(checks.values()))
                        for counter_key, global_counter, value in (
                                ("response_models", response_models, body.get("model")),
                                ("system_fingerprints", fingerprints, body.get("system_fingerprint")),
                                ("finish_reasons", finish_reasons, choice.get("finish_reason"))):
                            label = "<missing>" if value is None else str(value)
                            group[counter_key][label] += 1
                            global_counter[label] += 1
                        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                            value = usage.get(key)
                            if type(value) is int and value >= 0:
                                group["usage"][key] += value
                                token_totals[key] += value
                    output_items.append(captured)
                item["outputs"] = output_items
                all_runs.append(item)
            for entry in report["metrics"]:
                if entry["level"] != "aggregate":
                    continue
                group = grouped[entry["candidate_id"]]
                metric = entry["result"]
                counts = metric["counts"]
                check(counts["eligible"] == group["planned_units"], "metric_denominator_differs_from_plan", task_id)
                check(counts["eligible"] == sum(counts[key] for key in ("scored", "missing", "invalid", "excluded")), "metric_count_partition_invalid", task_id)
                group["metrics"].append({"metric_id": entry["metric_id"], **metric})
            tasks[task_id] = {"pipeline_report_status": report["status"], "quality_gate_verdict": report["verdict"],
                "before_report_sha256": sha(before_bytes), "after_report_sha256": sha(report_bytes),
                "previous_evaluation_id": report["previous_evaluation_id"], "candidates": grouped}
    finally:
        connection.close()
    if len(fingerprints) > 1:
        warnings.append("multiple_backend_fingerprints_observed; fingerprints_are_not_checkpoint_ids")
    if "length" in finish_reasons:
        warnings.append("truncated_outputs_preserved; no_answer_repair_or_retry_in_this_audit")
    return {"schema_version": "gymts.chatts.evidence-audit/1", "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": str(root), "summary_sha256": sha(summary_bytes), "pipeline_status": summary["status"],
        "audit_status": "pass" if not findings else "fail", "findings": findings, "warnings": warnings,
        "audit_scope": {"api_calls": 0, "credential_environment_read": False, "credential_files_read": False,
            "sqlite_read_only": True, "prompts_or_answers_exported": False,
            "private_label_check": "public_input_whitelist_and_exact_wire_projection; not_a_semantic_leakage_proof",
            "weights_checkpoint_verified": False},
        "totals": {"runs": len(all_runs), "http_calls": sum(x["http_calls"] for task in tasks.values() for x in task["candidates"].values()),
            "usage": dict(token_totals), "response_models": dict(response_models),
            "system_fingerprints": dict(fingerprints), "finish_reasons": dict(finish_reasons),
            "cas_artifacts_verified": len(cas.cache)}, "tasks": tasks, "runs": all_runs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New audit JSON file; existing files are never replaced")
    args = parser.parse_args(argv)
    if args.output.exists():
        print(json.dumps({"error": "audit_output_already_exists"}), file=sys.stderr)
        return 2
    try:
        report = audit_experiment(args.experiment)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"audit_status": report["audit_status"], "pipeline_status": report["pipeline_status"],
                          "findings": len(report["findings"]), "http_calls": report["totals"]["http_calls"],
                          "output": str(args.output.resolve())}, ensure_ascii=False))
        return 0 if report["audit_status"] == "pass" else 1
    except (AuditError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        # Never print data-bearing exception messages from artifact/JSON inputs.
        print(json.dumps({"error": str(error) if isinstance(error, AuditError) else type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
