"""Actual small CPU fit/score/rescore gate; synthetic inputs are not benchmark results.

Install the frozen core and this adapter into the configured native interpreter,
then invoke this file with -I -B from an unrelated directory. No mocks, paid
providers, source-tree imports, or core modifications are used.
"""
import argparse
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path

import gymts
from gymts import GymTS
from gymts.contracts import canonical_json, digest, utc_now
from gymts_timesigma.candidate import CALL, TRAINING_PROVENANCE
from gymts_timesigma.data import import_dataset
from gymts_timesigma.pipeline import run_experiment
from gymts_timesigma.trajectory import export_evidence


def core_tree(path):
    root = Path(path).resolve()
    paths = list((root / "gymts").rglob("*.py")) + [root / "setup.cfg"] if (root / "gymts").is_dir() else root.rglob("*")
    files = {str(item.relative_to(root)): {"sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
             "size_bytes": item.stat().st_size} for item in sorted(paths)
             if item.is_file() and "__pycache__" not in item.parts and item.suffix not in (".pyc", ".pyo")}
    if not files:
        raise ValueError("Core tree is empty")
    return {"path": str(root), "tree_sha256": digest(files), "files": files}


def run(output, source_repo, native_python, core_source, execution_seed=19, freeze_manifest=None, core_wheel=None):
    import numpy as np
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    roots = {"installed_core": Path(gymts.__file__).resolve().parent}
    if core_source is not None:
        roots["source_core"] = Path(core_source)
    before = {name: core_tree(path) for name, path in roots.items()}
    frozen = None
    if freeze_manifest is not None:
        frozen = json.loads(Path(freeze_manifest).read_text())
        current = {name: value["sha256"] for name, value in before["source_core"]["files"].items()}
        if current != frozen["files"] or hashlib.sha256(canonical_json(current)).hexdigest() != frozen["code_tree_sha256"]:
            raise AssertionError("Source core differs from the declared frozen tree")
    wheel_identity = None if core_wheel is None else {"path": str(Path(core_wheel).resolve()),
        "sha256": hashlib.sha256(Path(core_wheel).read_bytes()).hexdigest()}
    (output / "core-before.json").write_bytes(canonical_json(before))
    curve = output / "data/UTS/TODS/fixture"
    curve.mkdir(parents=True)
    train = np.asarray([math.sin(i / 5) + .1 * math.cos(i / 11) for i in range(96)], dtype="float64")
    test = np.asarray([math.sin((i + 96) / 5) + .1 * math.cos((i + 96) / 11) for i in range(64)], dtype="float64")
    labels = np.zeros(64, dtype="int64")
    labels[32:40] = 1
    test[32:40] += 3
    for name, values in (("train", train), ("test", test), ("test_label", labels)):
        np.save(curve / (name + ".npy"), values, allow_pickle=False)
    params = {"source_repo": str(Path(source_repo).resolve()), "python": str(Path(native_python).absolute()),
        "method": "AR", "hyper_params": {"p": 4, "epochs": 2, "batch_size": 8}, "timeout_seconds": 120}
    with GymTS(output / "state", integrations=("timesigma",)) as gym:
        imported = import_dataset(gym, output / "data", dataset="TODS", schema="naive", curve_id="fixture")
        experiment = run_experiment(gym, imported, params, execution_seed=execution_seed)
        if len(experiment["run_ids"]) != 1:
            raise AssertionError("Expected one pipeline x one Schema Run")
        run_id = experiment["run_ids"][0]
        original = gym.records.get_run(run_id)
        if original["result"]["status"] != "succeeded":
            raise AssertionError(original["result"]["errors"])
        result_digest, trace_digest = digest(original["result"]), digest(original["events"])
        repeated = gym.autobench.score(experiment["score_spec"])
        after_run = gym.records.get_run(run_id)
        if digest(after_run["result"]) != result_digest or digest(after_run["events"]) != trace_digest:
            raise AssertionError("Rescoring changed sealed execution evidence")
        if experiment["report"]["status"] != "completed" or repeated["status"] != "completed":
            raise AssertionError("Official scoring did not complete")
        refs = original["result"]["artifact_refs"]
        native_calls = [gym.artifacts.read_json(ref) for ref in refs if ref["schema_ref"] == CALL]
        operations = [row["operation"] for row in native_calls if row["phase"] == "completed"]
        if operations != ["fit", "score", "replay"]:
            raise AssertionError(operations)
        training = next(gym.artifacts.read_json(ref) for ref in refs if ref["schema_ref"] == TRAINING_PROVENANCE)
        if training["native_training_calls"] != 1 or training["test_available"] or training["training_objects_have_labels"]:
            raise AssertionError("Native training crossed the evaluation boundary")
        if training["randomness"] != {"requested_execution_seed": execution_seed,
                "effective_training_seed": execution_seed, "seed_source": "execution_context"}:
            raise AssertionError(training["randomness"])
        rows = gym.artifacts.read_json(original["result"]["result_ref"])
        prediction_evidence = rows[0]["payload"]["value"]["evidence"]
        if prediction_evidence["native_training_calls_during_infer"] or prediction_evidence["scaler_fit_calls_during_infer"] or not prediction_evidence["bitwise_equal"]:
            raise AssertionError("Frozen inference/replay evidence is incomplete")
        archive = export_evidence(gym, [run_id], output / "evidence.zip", roots=[experiment["experiment_ref"]])
        body = {"recorded_at": utc_now(), "scope": "real native CPU integration gate on explicit synthetic arrays; not benchmark-quality evidence",
            "run_id": run_id, "experiment": experiment, "repeated_report": repeated,
            "result_sha256": result_digest, "trace_sha256": trace_digest, "sealed_result_and_trace_unchanged": True,
            "native_operations": operations, "training_randomness": training["randomness"],
            "training_provenance": training, "prediction_evidence": prediction_evidence, "archive": archive,
            "versions": {name: metadata.version(name) for name in ("gymts", "gymts-timesigma", "timesigma", "numpy", "torch")},
            "frozen_core": frozen, "core_wheel": wheel_identity,
            "core_before": before, "core_after": {name: core_tree(path) for name, path in roots.items()}}
        if body["core_before"] != body["core_after"]:
            raise AssertionError("Core files changed during project integration")
        body["core_unchanged"] = True
        (output / "result.json").write_text(json.dumps(body, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        return {"status": "passed", "run_id": run_id, "result": str(output / "result.json"),
            "core_unchanged": True, "native_operations": operations, "training_randomness": training["randomness"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--core-source")
    parser.add_argument("--execution-seed", type=int, default=19)
    parser.add_argument("--freeze-manifest")
    parser.add_argument("--core-wheel")
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.source_repo, args.python, args.core_source, args.execution_seed, args.freeze_manifest, args.core_wheel), indent=2))


if __name__ == "__main__":
    main()
