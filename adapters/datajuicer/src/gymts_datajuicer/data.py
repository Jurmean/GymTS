"""Explicit preparation and post-seal resource registration, outside Candidate."""
import copy
import os
from pathlib import Path
import subprocess
from gymts.plugin_support import component, fail, unpack
from .common import dumps, loads, sha, source_row, validate_source, write_json
from .contracts import DATA_ROW

_GENERATOR = '''
import hashlib,json,random,sys
import numpy as np
from chatts.ts_generator.generate import generate_random_attributes,generate_time_series
seed,count,length=map(int,sys.argv[1:])
out=[]
for i in range(count):
 s=int.from_bytes(hashlib.sha256((str(seed)+':family:'+str(i)).encode()).digest()[:4],'big')
 random.seed(s);np.random.seed(s)
 attrs=generate_random_attributes(seq_len=length)
 values,attrs=generate_time_series(attrs,seq_len=length)
 out.append({'seed':s,'series':[round(float(v),4) for v in np.asarray(values).reshape(-1)]})
print('GYMTS_DATAJUICER='+json.dumps(out,allow_nan=False))
'''


def prepare_chatts(output, *, source_repo, python, train_count=12, holdout_count=4, seed=21, length=32):
    """Invoke actual ChatTS generators; split whole generated families first."""
    if (type(train_count) is not int or not 1 <= train_count <= 120 or type(holdout_count) is not int
        or not 1 <= holdout_count <= 120 or type(length) is not int or not 32 <= length <= 256):
        raise ValueError("Bounded preparation requires 1..120 train/holdout families and length 32..256")
    output, source = Path(output), Path(source_repo).resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = sorted((source / "chatts/ts_generator").glob("*.py")) + [source / "config/datagen_config.yaml"]
    def hashes():
        return {p.relative_to(source).as_posix(): sha(p.read_bytes()) for p in paths}
    before = hashes()
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
    native = subprocess.run([str(python), "-B", "-c", _GENERATOR, str(seed),
        str(train_count + holdout_count), str(length)], cwd=str(source), env={
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180, check=True)
    result = [line.split("=", 1)[1] for line in native.stdout.splitlines() if line.startswith("GYMTS_DATAJUICER=")]
    if len(result) != 1 or hashes() != before:
        raise ValueError("ChatTS changed or did not emit a complete source bundle")
    generated = loads(result[0])
    if len(generated) != train_count + holdout_count:
        raise ValueError("Native ChatTS generation count mismatch")
    rows, holdout, families = [], [], set()
    for index, entry in enumerate(generated):
        family = sha({"source": revision, "seed": entry["seed"], "series": entry["series"]})
        if family in families:
            raise ValueError("Generated family identities overlap")
        families.add(family)
        if index < train_count:
            rows.append(source_row(entry["series"], family_id=family, sample_id=sha({"family": family, "row": 0}),
                                   operation="max" if index % 2 == 0 else "min"))
        else:
            holdout.append({"family_id": family, "series_sha256": sha(entry["series"])})
    # Explicit negative/duplicate fixtures exercise actual native membership
    # changes. They derive from training families and do not touch holdout.
    for index in range(min(2, train_count)):
        duplicate = copy.deepcopy(rows[index])
        duplicate["sample_id"] = sha({"duplicate_of": duplicate["sample_id"]})
        rows.append(duplicate)
    short = copy.deepcopy(rows[0])
    short.update(sample_id=sha({"short_fixture": short["sample_id"]}), text="short")
    rows.append(short)
    validate_source(rows)
    provenance = {"generator": "chatts.ts_generator.generate:generate_random_attributes+generate_time_series",
        "source_repo": str(source), "source_revision": revision, "source_files_sha256": before,
        "license": "MIT", "seed": seed, "sequence_length": length,
        "split_rule": "whole-generated-family;first-fixed-train-count;before-any-datajuicer-operation",
        "train_families": train_count, "holdout_families": holdout_count,
        "fixtures": {"duplicate_rows": min(2, train_count), "short_rows": 1}}
    source_revision = sha({"rows": rows, "holdout": holdout, "provenance": provenance})
    public = {"source_revision": source_revision, "rows": rows}
    reference = dict(public, holdout_families=[row["family_id"] for row in holdout],
                     holdout_series_sha256=[row["series_sha256"] for row in holdout])
    write_json(output / "public.json", public)
    write_json(output / "reference.json", reference)
    write_json(output / "provenance.json", provenance)
    return {"public": public, "reference": reference, "provenance": provenance}


def sealed_value(gym, run_id):
    run = gym.records.get_run(run_id)
    if run["result"] is None or run["result"]["status"] != "succeeded":
        fail("invalid_state", "Derived resources require a sealed successful native Run")
    # Consume the public sealed result artifact, rather than guessing an event
    # kind. F0 emits task_result events and stores records as list or {results}.
    values = gym.artifacts.read_json(run["result"]["result_ref"])
    if isinstance(values, dict):
        values = values.get("results")
    if not isinstance(values, list):
        fail("schema_mismatch", "Sealed Run does not contain TaskResult records")
    if len(values) != 1 or values[0]["status"] != "valid":
        fail("invalid_state", "Derived publication requires exactly one valid pipeline result")
    return run, unpack(values[0]["payload"], gym.artifacts)


def _authorize_quality(gym, run_id, reference):
    if reference is None or reference.get("schema_ref") != "gymts.evaluation-report/1":
        fail("permission_denied", "Training publication requires an immutable formal quality report reference")
    report = gym.artifacts.read_json(reference)
    if report["status"] != "completed" or report["scorer_ref"] != component("datajuicer-quality"):
        fail("permission_denied", "Training publication requires a completed Data-Juicer QualityScorer report")
    entries = gym.artifacts.read_json(report["run_manifest_ref"])["entries"]
    if len(entries) != 1 or entries[0]["run_id"] != run_id or entries[0]["status"] != "succeeded":
        fail("permission_denied", "Quality report must evaluate exactly this successful sealed Run")
    plan = gym.artifacts.read_json(report["plan_ref"])
    spec = gym.artifacts.read_json(plan["spec_ref"])
    if (plan["evaluation_id"] != report["evaluation_id"] or spec["scoring"]["scorer"] != {
        "adapter": "datajuicer-quality", "version": "1.0.0", "params": {}}):
        fail("permission_denied", "Quality report identity does not match its formal evaluation plan")
    for metric in ("lineage_integrity", "holdout_clean"):
        scores = [row["result"] for row in report["metrics"] if row["level"] == "aggregate" and row["metric_id"] == metric]
        if (len(scores) != 1 or scores[0]["status"] != "ready" or scores[0]["value"] != 1
            or scores[0]["counts"] != {"eligible": 1, "scored": 1, "missing": 0, "invalid": 0, "excluded": 0}):
            fail("permission_denied", "Training publication requires complete passing " + metric + " evidence")
        indices = [index for index, gate in enumerate(spec["comparison"]["gates"]) if gate["metric"] == metric
            and gate["target"] == "absolute" and gate["operator"] == "ge" and gate["threshold"] == 1
            and gate["scope"] == "aggregate"]
        if not indices or not any(gate["gate_index"] in indices and gate["status"] == "pass"
                                  for gate in report["gate_results"]):
            fail("permission_denied", "Formal quality plan lacks a passing " + metric + " gate")
    return report


def register_derived(gym, run_id, dataset_id, *, quality_report_ref=None):
    """Caller-authorized DatasetCatalog ingestion; never invoked by Candidate.

    This preserves all actual outputs, including incorrect answers. A quality
    report does not silently promote generated labels to verified gold.
    """
    run, value = sealed_value(gym, run_id)
    quality_report = _authorize_quality(gym, run_id, quality_report_ref)
    raw = value["export_text"].encode()
    if sha(raw) != value["export_sha256"]:
        fail("artifact_integrity", "Sealed native export hash mismatch")
    parsed = [loads(line) for line in value["export_text"].splitlines() if line.strip()]
    if parsed != value["rows"] or not parsed:
        fail("artifact_integrity", "Empty or inconsistent derived output cannot be registered for training")
    source_fields = {"sample_id", "family_id", "split", "series", "operation", "text"}
    allowed_fields = source_fields | {"query", "response", "__dj__stats__", "__dj__hash"}
    if any(set(row) - allowed_fields for row in parsed):
        fail("permission_denied", "Derived training rows contain undeclared fields")
    validate_source([{key: row[key] for key in source_fields} for row in parsed])
    exported = []
    for index, row in enumerate(parsed):
        prompt = [{"role": "user", "content": "Given this time series and requested operation, return only "
            "a JSON object with one numeric key value.\n" + dumps({"series": row["series"],
                "operation": row["operation"], "family_id": row["family_id"]})}]
        exported.append(dict(row, sample_id=sha({"run_id": run_id, "row_index": index, "row": row}),
            parent_sample_id=row["sample_id"], label_status="model_generated_unverified",
            prompt=prompt, completion=row["response"]))
    catalog = gym.environment_ts.datasets
    public_asset = catalog.publish_asset("".join(dumps(row) + "\n" for row in exported).encode(), media_type="application/jsonl")
    native_asset = catalog.publish_asset(raw, media_type="application/jsonl")
    lineage_asset = catalog.publish_asset(dumps({"run_id": run_id, "run_result_ref": run["result_ref"],
        "execution_snapshot_ref": run["execution_snapshot_ref"], "stages": value["stages"],
        "identity": value["identity"]}).encode(), media_type="application/json")
    quality_asset = catalog.publish_asset(dumps(quality_report).encode(), media_type="application/json")
    manifest = {"protocol_version": "gymts.source-dataset/1", "dataset_id": dataset_id, "config": "default",
        "revision": None, "schema_ref": DATA_ROW, "reader_ref": component("gymts.jsonl-reader", "1.0.0"),
        "features": {"modality": "timeseries+text", "label_status": "model_generated_unverified",
                     "training_projection": "timeseries-operation-chat/1",
                     "source_run_id": run_id, "native_export_sha256": value["export_sha256"]},
        "splits": {"train": {"row_count": len(exported), "split_origin": "explicit_train_only_derived_run",
            "input_indices": [0], "target_indices": []}},
        "usage_policy": {"allowed_uses": ["training", "dataset_build", "runtime"], "training_allowed": True},
        "source_files": [{"name": "native-derived.jsonl", "asset_ref": native_asset},
                         {"name": "lineage.json", "asset_ref": lineage_asset}],
        "importer_ref": component("gymts-datajuicer-sealed-derivation", "0.1.0"),
        "inputs": [public_asset], "series": [], "targets": [], "quality_report_ref": quality_asset, "card_ref": None}
    return catalog.register_dataset(manifest)
