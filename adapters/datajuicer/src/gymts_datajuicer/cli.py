"""Installed-wheel CLI. Commands never call a cloud model or upload assets."""
import argparse
import importlib.metadata
from pathlib import Path
import sys
from .common import dumps, loads, sha, write_json


def model_identity(path):
    root = Path(path).resolve()
    names = {"config.json", "generation_config.json", "tokenizer_config.json", "tokenizer.json",
             "vocab.json", "merges.txt", "special_tokens_map.json"}
    paths = sorted(p for p in root.iterdir() if p.is_file() and
                   (p.name in names or p.name.endswith(".safetensors") or p.name.endswith(".safetensors.index.json")))
    if not any(p.name.endswith(".safetensors") for p in paths) or not (root / "config.json").is_file():
        raise ValueError("Model directory needs actual safetensors and config.json")
    import struct
    import math
    tensors = {}
    dtype_bytes = {"BOOL": 1, "I8": 1, "U8": 1, "F8_E4M3": 1, "F8_E5M2": 1, "I16": 2,
                   "U16": 2, "F16": 2, "BF16": 2, "I32": 4, "U32": 4, "F32": 4, "I64": 8, "U64": 8, "F64": 8}
    for shard in (p for p in paths if p.name.endswith(".safetensors")):
        size = shard.stat().st_size
        with shard.open("rb") as stream:
            prefix = stream.read(8)
            if len(prefix) != 8:
                raise ValueError("Truncated safetensors prefix: " + shard.name)
            length = struct.unpack("<Q", prefix)[0]
            if not 2 <= length <= min(100 * 1024 * 1024, size - 8):
                raise ValueError("Invalid/truncated safetensors header: " + shard.name)
            header = loads(stream.read(length))
        maximum, ranges = 0, []
        for name, tensor in header.items():
            if name == "__metadata__":
                continue
            start, end = tensor["data_offsets"]
            shape, dtype = tensor["shape"], tensor["dtype"]
            if (dtype not in dtype_bytes or any(type(v) is not int or v < 0 for v in shape)
                or type(start) is not int or type(end) is not int or not 0 <= start <= end <= size - 8 - length
                or end - start != math.prod(shape) * dtype_bytes[dtype]):
                raise ValueError("Invalid/truncated tensor data: " + shard.name + ":" + name)
            if name in tensors:
                raise ValueError("Repeated tensor across model shards: " + name)
            tensors[name] = shard.name
            ranges.append((start, end))
            maximum = max(maximum, end)
        ordered = sorted(ranges)
        if not ranges or maximum != size - 8 - length or any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Invalid tensor payload extent: " + shard.name)
    index = root / "model.safetensors.index.json"
    if index.exists() and loads(index.read_text())["weight_map"] != tensors:
        raise ValueError("Safetensors index does not match actual shard tensors")
    files = {}
    import hashlib
    for p in paths:
        h = hashlib.sha256()
        with p.open("rb") as stream:
            while block := stream.read(8 * 1024 * 1024):
                h.update(block)
        files[p.name] = {"sha256": h.hexdigest(), "size_bytes": p.stat().st_size}
    return {"local_path": str(root), "files": files, "tree_sha256": sha(files)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    source = sub.add_parser("prepare-source", help="Run ChatTS numerical generator and freeze train/holdout families")
    source.add_argument("--output", required=True)
    source.add_argument("--chatts", required=True)
    source.add_argument("--python", required=True)
    source.add_argument("--train-count", type=int, default=12)
    source.add_argument("--holdout-count", type=int, default=4)
    source.add_argument("--seed", type=int, default=21)
    source.add_argument("--length", type=int, default=32)
    identity = sub.add_parser("model-identity", help="Hash local model and tokenizer without loading them")
    identity.add_argument("--model", required=True)
    identity.add_argument("--output", required=True)
    run = sub.add_parser("run", help="Real native pipeline in one GymTS Run, then independent AutoBench evaluation")
    run.add_argument("--root", required=True)
    run.add_argument("--source", required=True)
    run.add_argument("--native-python", required=True)
    run.add_argument("--upstream", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--model-identity", required=True)
    run.add_argument("--work", required=True)
    run.add_argument("--timeout", type=int, default=1200)
    run.add_argument("--max-new-tokens", type=int, default=192)
    preflight = sub.add_parser("preflight", help="Native CPU full-recipe parse/instantiate/spawn plus real filter/dedup; no generation")
    preflight.add_argument("--output", required=True)
    preflight.add_argument("--source", required=True)
    preflight.add_argument("--native-python", required=True)
    preflight.add_argument("--upstream", required=True)
    preflight.add_argument("--model", required=True)
    preflight.add_argument("--model-identity", required=True)
    preflight.add_argument("--max-new-tokens", type=int, default=192)
    for name in ("rescore", "register-derived"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True)
        p.add_argument("--report", required=True)
        p.add_argument("--output", required=True)
        if name == "register-derived":
            p.add_argument("--dataset-id", required=True)
            p.add_argument("--report-ref", help="Formal report ArtifactRef JSON; defaults to REPORTNAME.ref.json")
    args = parser.parse_args(argv)
    if args.command == "prepare-source":
        from .data import prepare_chatts
        result = prepare_chatts(args.output, source_repo=args.chatts, python=args.python,
            train_count=args.train_count, holdout_count=args.holdout_count, seed=args.seed, length=args.length)
        print(dumps({"source_revision": result["public"]["source_revision"], "train_rows": len(result["public"]["rows"]),
                     "holdout_families": len(result["reference"]["holdout_families"])}))
        return
    if args.command == "model-identity":
        value = model_identity(args.model)
        write_json(args.output, value)
        print(dumps({"tree_sha256": value["tree_sha256"], "files": len(value["files"])}))
        return
    if args.command == "preflight":
        from .preflight import run_preflight
        result = run_preflight(output=args.output, source=args.source, worker_python=args.native_python,
            upstream=args.upstream, model_path=args.model, model_identity=loads(Path(args.model_identity).read_text()),
            max_new_tokens=args.max_new_tokens)
        print(dumps(result))
        return
    from gymts import GymTS
    from .experiments import evaluation_spec, rescore
    root = Path(args.root).resolve()
    with GymTS(root / "records", integrations=("datajuicer",), data_home=root / "data", cache_home=root / "cache") as gym:
        if args.command == "run":
            source = Path(args.source)
            model = loads(Path(args.model_identity).read_text())
            if model["local_path"] != str(Path(args.model).resolve()):
                raise ValueError("Model identity belongs to another directory")
            # Resolving venv/bin/python follows its symlink to the base Python
            # and loses pyvenv.cfg discovery and the installed worker package.
            params = {"worker_python": str(Path(args.native_python).absolute()), "upstream": str(Path(args.upstream).resolve()),
                "model_path": str(Path(args.model).resolve()), "model_identity": model, "timeout_seconds": args.timeout,
                "max_new_tokens": args.max_new_tokens, "work_root": str(Path(args.work).resolve())}
            spec = evaluation_spec(gym, loads((source / "public.json").read_text()),
                loads((source / "reference.json").read_text()), params,
                provenance=loads((source / "provenance.json").read_text()))
            write_json(root / "evaluation-spec.json", spec)
            report = gym.autobench.evaluate(spec)
            write_json(root / "evaluation.json", report)
            write_json(root / "evaluation.ref.json", gym.autobench.last_report_ref)
            print(dumps({"evaluation_id": report["evaluation_id"], "verdict": report["verdict"],
                         "report": str(root / "evaluation.json")}))
            if report["status"] != "completed" or report["verdict"] != "pass" or report["coverage"]["failed_runs"]:
                raise SystemExit(1)
            return
        report = loads(Path(args.report).read_text())
        plan = gym.artifacts.read_json(report["plan_ref"])
        spec = gym.artifacts.read_json(plan["spec_ref"])
        if args.command == "rescore":
            result = rescore(gym, spec, report)
        else:
            from .data import register_derived
            entries = gym.artifacts.read_json(report["run_manifest_ref"])["entries"]
            if len(entries) != 1:
                raise ValueError("Expected one sealed pipeline Run")
            reference_path = Path(args.report_ref) if args.report_ref else Path(args.report).with_suffix(".ref.json")
            reference = loads(reference_path.read_text())
            if gym.artifacts.read_json(reference) != report:
                raise ValueError("Report JSON differs from its immutable formal ArtifactRef")
            result = register_derived(gym, entries[0]["run_id"], args.dataset_id, quality_report_ref=reference)
        write_json(args.output, result)
        if args.command == "rescore":
            write_json(Path(args.output).with_suffix(".ref.json"), gym.autobench.last_report_ref)
        print(dumps({"output": str(args.output), "command": args.command}))
        if args.command == "rescore" and (result["status"] != "completed" or result["verdict"] != "pass"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
