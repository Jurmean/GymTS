"""Public SDK evaluation/score construction; only this owner opens references."""
import copy
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import re
import zipfile

from gymts.contracts import digest, inline, utc_now
from .contracts import ALIGNMENT, OUTCOME, SNAPSHOT


def _installed_core():
    import gymts
    distribution = importlib.metadata.distribution("gymts")
    version = distribution.version
    if not re.fullmatch(r"0\.[56]\.(0|[1-9][0-9]*)", version) or gymts.__version__ != version:
        raise ValueError("This adapter requires a matching installed stable GymTS 0.5.x or 0.6.x distribution")
    installed_init = Path(distribution.locate_file("gymts/__init__.py")).resolve()
    if Path(gymts.__file__).resolve() != installed_init:
        raise ValueError("GymTS import does not come from the installed distribution")
    direct = distribution.read_text("direct_url.json")
    if direct and json.loads(direct).get("dir_info", {}).get("editable"):
        raise ValueError("Freeze a wheel installation, not an editable source installation")
    root = Path(gymts.__file__).resolve().parent.parent
    files = {str(path.relative_to(root)): path.read_bytes() for path in (root / "gymts").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo")}
    if version == "0.5.0" and len(files) != 39:
        raise ValueError("GymTS 0.5.0 must contain the complete 39-file frozen package")
    return version, root, files


def freeze_core(wheel_path, *, expected_wheel_sha256=None):
    """Match actual installed core bytes to a supplied wheel; no model imports.

    The resulting portable identity has no local paths or invented Git origin.
    It records the supplied archive hash and verifies every installed payload
    file against its original bytes in that wheel.
    """
    version, _, installed = _installed_core()
    wheel_path = Path(wheel_path)
    content = wheel_path.read_bytes()
    wheel_sha = hashlib.sha256(content).hexdigest()
    if expected_wheel_sha256 is not None and wheel_sha != expected_wheel_sha256:
        raise ValueError("Provided core wheel SHA-256 differs from the expected hash")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Core wheel contains duplicate members")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Core wheel must contain one distribution metadata file")
        from email.parser import BytesParser
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        if metadata["Name"] != "gymts" or metadata["Version"] != version:
            raise ValueError("Core wheel name/version differs from the actual installed GymTS")
        payloads = {name: archive.read(name) for name in names if name.startswith("gymts/") and not name.endswith("/")}
        if set(payloads) != set(installed):
            raise ValueError("Core wheel and installed package file membership differ")
        if any(payloads[name] != installed[name] for name in payloads):
            raise ValueError("Installed core bytes differ from the supplied wheel payload")
    return {"core_version": version, "wheel_filename": wheel_path.name, "wheel_sha256": wheel_sha,
        "verification": "installed-package-bytes-match-supplied-wheel",
        "installed_files": {name: hashlib.sha256(value).hexdigest() for name, value in sorted(payloads.items())}}


def verify_frozen_core(identity_path):
    version, root, installed = _installed_core()
    expected = json.loads(Path(identity_path).read_text())
    if expected.get("core_version") != version or set(expected["installed_files"]) != set(installed):
        raise ValueError("Frozen core version or complete file membership differs from the installation")
    if not re.fullmatch(r"[0-9a-f]{64}", expected["wheel_sha256"]):
        raise ValueError("Frozen core identity requires a complete wheel SHA-256")
    for relative, sha in expected["installed_files"].items():
        if hashlib.sha256(installed[relative]).hexdigest() != sha:
            raise ValueError("Installed frozen core differs: " + relative)
    return {"core_import": str((root / "gymts/__init__.py").resolve()), "wheel_sha256": expected["wheel_sha256"],
        "verified_files": len(expected["installed_files"]), "git_commit": expected.get("git_commit")}


def build_evaluation(gym, public, private, candidate_params):
    if public["dataset_revision"] != private["dataset_revision"]:
        raise ValueError("Public and private view revisions differ")
    samples, targets = public["samples"], private["targets"]
    ids = [row["sample_id"] for row in samples]
    if not ids or len(set(ids)) != len(ids) or len({row["sample_id"] for row in targets}) != len(targets) or set(ids) != {row["sample_id"] for row in targets}:
        raise ValueError("Public questions and private references must align exactly")
    revision = public["dataset_revision"]
    alignment = [{"dataset_revision": revision, "sample_id": token} for token in ids]
    ref = gym.artifacts.save_json(public, SNAPSHOT)
    private_ref = gym.artifacts.save_json(private, "gymts.json/1")
    available = utc_now()
    outcomes = []
    for target in targets:
        if target["allowed_uses"] != ["evaluation"]:
            raise ValueError("References must be evaluation-only")
        outcomes.append({"outcome_id": "enginemt-gold-" + digest({"revision": revision, "sample_id": target["sample_id"]}),
            "revision": "1", "alignment_key": {"dataset_revision": revision, "sample_id": target["sample_id"]},
            "payload": inline({key: target[key] for key in ("answer", "stage", "reference_status")}, OUTCOME),
            "event_time": ids.index(target["sample_id"]), "available_at": available, "recorded_at": available,
            "source_ref": private_ref, "supersedes_ref": None, "allowed_uses": ["evaluation"]})
    target_ref = gym.artifacts.save_json(outcomes, "gymts.outcome-records/1")
    view = {"view_id": "enginemt-gold-" + target_ref["revision"], "revision": target_ref["revision"],
        "source_refs": [target_ref], "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"),
        "as_of": None, "purpose": "evaluation"}
    case = {"evaluation_case_id": "enginemt-fixed-view", "tags": {"dataset": "EngineMT-QA", "view_revision": revision},
        "scene": {"environment": {"protocol_version": "gymts.environment/1", "adapter": "itformer-snapshot", "version": "1.0.0",
            "source": {"kind": "dataset", "locator": "artifact://public-enginemt-qa", "revision": revision,
                "connection": {"artifact_refs": [ref]}, "credential_ref": None}, "mapping": {}, "options": {"row_count": len(ids)}},
            "task": {"plugin": "itformer-qa", "version": "1.0.0", "params": {}},
            "binding": {"variables": {"sample": {"source": "sample", "unit": "sample", "transform": None}}, "operations": {}}},
        "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": len(ids)},
            "feedback_until": None, "seed": 42, "learning": {"prepare": "load_only", "online": "frozen",
                "training_view": None, "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
            "limits": {"max_inputs": len(ids), "max_operations": None, "max_turns_per_case": 1, "max_wall_time_s": 3600}},
        "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
            "model_calls": "io", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []}}
    return {"protocol_version": "gymts.evaluation/1", "name": "ITFormer official EngineMT-QA fixed view",
        "purpose": "acceptance", "cases": [case], "candidates": [{"candidate_id": "native-itformer",
            "spec": {"adapter": "itformer-native", "version": "1.0.0", "artifact": None, "params": copy.deepcopy(candidate_params), "inherited_state": []}}],
        "baseline_id": None, "repetitions": {"count": 1, "seeds": [42]},
        "scoring": {"scorer": {"adapter": "itformer-reference", "version": "1.0.0", "params": {"expected_alignments": alignment}},
            "outcomes": {"sources": [view], "as_of": available}, "alignment": {"schema_ref": ALIGNMENT,
                "keys": ["dataset_revision", "sample_id"], "matching": "exact", "params": {}, "duplicate_policy": "error"},
            "metrics": ["answer_exact_match", "lexical_token_f1", "format_valid"],
            "evidence_requirements": {"min_scored": len(ids), "min_coverage": 1, "overrides": {}},
            "missing_outcome_policy": "report_insufficient"},
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
            "baseline_method": "difference", "gates": [
                {"metric": "run_failure_rate", "target": "absolute", "candidate_ids": None, "for_metric": None,
                    "operator": "le", "threshold": 0, "scope": "aggregate"},
                {"metric": "scored_coverage", "target": "absolute", "candidate_ids": None, "for_metric": "answer_exact_match",
                    "operator": "ge", "threshold": 1, "scope": "aggregate"}]},
        "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}


def score_spec(gym, evaluation_spec, report):
    manifest = gym.artifacts.read_json(report["run_manifest_ref"])
    # Evaluation run manifests retain all unit identities and unavailable runs.
    units = gym.artifacts.read_json(report["plan_ref"])["expected_units"]
    executions = {row["unit_id"]: row for row in manifest["entries"]}
    runs = []
    for unit in units:
        execution = executions[unit["unit_id"]]
        runs.append({key: copy.deepcopy(unit[key]) for key in ("unit_id", "evaluation_case_id", "candidate_id", "repetition", "tags")})
        runs[-1].update(run_id=execution["run_id"], unavailable_reason=None if execution["run_id"] else "original_run_unavailable",
            unit_spec_ref=unit["resolved_spec_ref"])
    result = {key: copy.deepcopy(evaluation_spec[key]) for key in (
        "name", "purpose", "baseline_id", "scoring", "comparison", "failure_policy")}
    result.update(protocol_version="gymts.score/1", runs=runs, previous_evaluation_id=report["evaluation_id"])
    return result
