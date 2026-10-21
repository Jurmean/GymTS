"""Explicit, bounded native commands. No training or downloads on registration."""
import argparse
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from gymts import GymTS
from .contracts import PINNED_REVISION
from .identity import freeze_core, model_identity, verify_core
from .wire import sha


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def worker_environment(repository, core_identity, output, *, gpu_devices=(), bridge=None):
    # Inherited credentials/proxies/PYTHONPATH are deliberately absent.
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "LD_LIBRARY_PATH", "CUDA_HOME", "CUDA_PATH")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "1",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": ",".join(str(value) for value in gpu_devices),
        "GYMTS_AREAL_REPOSITORY": str(Path(repository).resolve(strict=True)),
        "GYMTS_FROZEN_CORE_IDENTITY": str(Path(core_identity).resolve(strict=True)),
        "XDG_CACHE_HOME": str(Path(output) / "cache"), "HF_HOME": str(Path(output) / "cache/huggingface")})
    if bridge:
        env.update(GYMTS_AREAL_BRIDGE_SOCKET=str(bridge.path), GYMTS_AREAL_BRIDGE_ID=bridge.bridge_id)
    return env


def run_worker(python, module, path, *, env, output, timeout):
    output = Path(output)
    with output.open("xb") as stream:
        environment = dict(env, GYMTS_AREAL_PARENT_PID=str(os.getpid()))
        # Upstream get_py_cmd deliberately uses the bare 'python3' executable.
        # The declared isolated interpreter must also own every native sub-launch.
        environment["PATH"] = str(Path(python).absolute().parent) + os.pathsep + environment.get("PATH", os.defpath)
        process = subprocess.Popen([str(Path(python).absolute()), "-I", "-B", "-m", "gymts_areal.lifecycle", module, str(Path(path).resolve())],
            cwd=str(output.parent), env=environment, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        previous_term = None
        def stop_owned_worker(signum, _frame):
            raise SystemExit(128 + signum)
        if threading.current_thread() is threading.main_thread():
            previous_term = signal.signal(signal.SIGTERM, stop_owned_worker)
        try:
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as error:
                raise TimeoutError("Bounded native worker wall-clock budget exhausted; log and sealed Runs retained") from error
        finally:
            if previous_term is not None:
                signal.signal(signal.SIGTERM, previous_term)
            # Fixed native scheduler/RPC/SGLang children inherit this exact group.
            # Retain descendant identities too, for a child which explicitly changes its session.
            try:
                import psutil
                owned = psutil.Process(process.pid).children(recursive=True)
            except ImportError:
                owned = []  # Fixed upstream children still inherit the owned process group.
            except psutil.NoSuchProcess:
                owned = []
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            for child in owned:
                try:
                    if child.is_running(): child.kill()
                except psutil.NoSuchProcess:
                    pass
            process.wait(timeout=10)
    if code:
        raise RuntimeError("Native worker failed with exit code " + str(code) + "; inspect " + str(output))


def prepare(args):
    from gymts_rl.data import prepare_dataset
    verify_core(args.core_identity)
    with GymTS(args.store, integrations=["rl", "areal"]) as gym:
        result = prepare_dataset(gym, args.output, gsm8k_dir=args.gsm8k,
            chatts_source=args.chatts, python=args.python, seed=args.seed,
            train_limit=args.train_per_source, eval_limit=args.eval_per_source,
            chatts_train=args.train_per_source, chatts_eval=args.eval_per_source, sequence_length=32)
    return {"status": "prepared", "prepared": result["output_dir"] + "/manifest.json", "counts": result["counts"]}


def train_or_preflight(args, preflight=False):
    from .bridge import BridgeService
    verify_core(args.core_identity)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    prepared = json.loads(Path(args.prepared).read_text())
    core_identity = str(Path(args.core_identity).resolve(strict=True))
    with GymTS(args.store, integrations=["rl", "areal"]) as gym:
        public = gym.artifacts.read_json(prepared["snapshot_ref"])["samples"]
        train = [copy.deepcopy(row) for row in public if row["split"] == "train"]
        if not train or args.group_size < 2 or args.group_size > 8:
            raise ValueError("Native grouped RL requires public training data and group size in [2,8]")
        settings = {"output": str(output), "model": str(Path(args.model).resolve(strict=True)), "public_train": train,
            "trial": output.name, "seed": args.seed, "group_size": args.group_size,
            "max_new_tokens": args.max_new_tokens, "max_length": args.max_length,
            "episode_seconds": args.episode_seconds, "learning_rate": args.learning_rate,
            "max_model_requests": args.max_model_requests,
            "cpu_preflight_only": preflight}
        if not preflight:
            if len(args.gpu_devices) != 2 or len(set(args.gpu_devices)) != 2 or len(args.gpu_uuids) != 2:
                raise ValueError("Pass exactly two explicitly allocated physical GPU indices and matching UUIDs")
            settings.update(model_identity=model_identity(args.model), gpu_uuids=args.gpu_uuids)
        write(output / "public-native-settings.json", settings)
        service = BridgeService(gym, prepared, output / "private-bridge", max_episodes=len(train) * args.group_size).start()
        status, failure = "failed", None
        try:
            environment = worker_environment(args.upstream, core_identity, output,
                gpu_devices=() if preflight else args.gpu_devices, bridge=service)
            run_worker(args.python, "gymts_areal.native_train", output / "public-native-settings.json",
                env=environment, output=output / "native-worker.log", timeout=300 if preflight else args.seconds)
            summary = service.summary()
            if not preflight:
                from .checkpoint import publish_native_checkpoint
                native = json.loads((output / "native-training-result.json").read_text())
                published = publish_native_checkpoint(gym, prepared, native, summary, args.model)
                write(output / "checkpoint-bundle.json", published)
            status = "cpu_preflight_passed" if preflight else "checkpointed"
        except BaseException as error:
            status = "failed"
            failure = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            drain_error = None
            try:
                service.close()
            except Exception as error:
                drain_error, status = error, "failed"
                failure = {"original": failure, "cleanup": {"type": type(error).__name__, "message": str(error)}}
            summary = service.summary()
            summary.update(status=status, error=failure, native_revision=PINNED_REVISION,
                source_dataset_manifest_ref=prepared["manifest_ref"], core_identity=verify_core(core_identity))
            # Native tensors remain in referenced CAS shards, not duplicated in a human summary.
            public_summary = copy.deepcopy(summary)
            for row in public_summary["episodes"]:
                row.pop("native_tensors", None)
            summary_ref = gym.artifacts.save_json(public_summary, "gymts.json/1")
            write(output / "training-parent.json", dict(public_summary, summary_ref=summary_ref))
            if drain_error is not None:
                raise drain_error
    return {"status": status, "output": str(output)}


def publish(args):
    """Deploy an already saved native checkpoint without rerunning training."""
    from .checkpoint import publish_native_checkpoint
    from gymts_rl.pipeline import _sources
    verify_core(args.core_identity)
    prepared = json.loads(Path(args.prepared).read_text())
    parent = json.loads(Path(args.training_parent).read_text())
    native = json.loads(Path(args.native).read_text())
    destination = Path(args.output)
    if destination.exists():
        raise ValueError("Choose a new deployment publication output; previous artifacts stay immutable")
    with GymTS(args.store, integrations=["rl", "areal"]) as gym:
        committed = gym.artifacts.read_json(parent["summary_ref"])
        if {key: value for key, value in parent.items() if key != "summary_ref"} != committed:
            raise ValueError("Training parent differs from its immutable CAS revision")
        if parent["source_dataset_manifest_ref"] != prepared["manifest_ref"]:
            raise ValueError("Publication source differs from the sealed training parent")
        _sources(gym, prepared, prepared["train_sample_ids"], "train")
        result = publish_native_checkpoint(gym, prepared, native, parent, args.model,
            tokenizer_compatibility=args.tokenizer_compatibility)
        result["training_parent_ref"] = parent["summary_ref"]
        result["publication_ref"] = gym.artifacts.save_json(result, "gymts.json/1")
        write(destination, result)
    return {"status": "published", "output": str(destination.resolve())}


def evaluate(args):
    # This CLI invocation is a fresh process. It never imports the native trainer/TIR.
    from gymts_rl.evaluation import checkpoint_evaluation_spec
    verify_core(args.core_identity)
    prepared = json.loads(Path(args.prepared).read_text())
    bundle = json.loads(Path(args.bundle).read_text())
    with GymTS(args.store, integrations=["rl", "areal"]) as gym:
        specification = checkpoint_evaluation_spec(gym, prepared, bundle["bundle_ref"], prepared["eval_sample_ids"],
            seeds=(args.seed,), generation={"max_new_tokens": args.max_new_tokens, "do_sample": False},
            load={"device": args.device, "dtype": args.dtype, "base_model_path": str(Path(args.model).resolve(strict=True))})
        report = gym.autobench.evaluate(specification)
        write(args.output, report)
        require_complete_evaluation(report)
    return {"status": report["status"], "report": str(Path(args.output).resolve())}


def rescore(args):
    from gymts_rl.evaluation import rescore_checkpoint_evaluation
    from gymts_rl.candidate import LocalHFCandidate
    from gymts_areal.candidate import LiveTIRCandidate
    verify_core(args.core_identity)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Heavy model or native trainer construction is forbidden during independent re-scoring")
    LocalHFCandidate.prepare = forbidden
    LiveTIRCandidate.prepare = forbidden
    report = json.loads(Path(args.report).read_text())
    with GymTS(args.store, integrations=["rl", "areal"]) as gym:
        manifest = gym.artifacts.read_json(report["run_manifest_ref"])
        runs = [row["run_id"] for row in manifest["entries"] if row["run_id"]]
        before = {token: sha(gym.records.get_run(token)) for token in runs}
        after_report = rescore_checkpoint_evaluation(gym, report)
        if any(sha(gym.records.get_run(token)) != before[token] for token in runs):
            raise AssertionError("Independent re-scoring changed sealed run evidence")
        write(args.output, {"report": after_report, "heavy_backends_forbidden": True, "sealed_runs_unchanged": True,
                            "original_evaluation_id": report["evaluation_id"]})
        require_complete_evaluation(after_report)
    return {"status": after_report["status"], "rescore": str(Path(args.output).resolve())}


def require_complete_evaluation(report):
    """Require complete execution/scoring without inventing a quality gate."""
    coverage = report["coverage"]
    metrics = report["metrics"]
    scored = bool(metrics) and all(
        entry["result"]["status"] == "ready"
        and entry["result"]["counts"]["eligible"] > 0
        and entry["result"]["counts"]["scored"] == entry["result"]["counts"]["eligible"]
        and not any(entry["result"]["counts"][field] for field in ("missing", "invalid", "excluded"))
        for entry in metrics)
    # AutoBenchTS deliberately withholds an acceptance verdict when no quality
    # gates were requested. Retain that verdict; only this exact evidence-complete
    # case may count as a completed engineering evaluation.
    verdict_ok = (report["verdict"] == "pass" and all(gate["status"] == "pass" for gate in report["gate_results"])) or (
        report["verdict"] == "insufficient_evidence" and not report["gate_results"]
        and report["reasons"] == ["no_acceptance_gate"])
    if (report["status"] != "completed" or not verdict_ok or report["errors"] or not scored or
            coverage["expected_units"] <= 0 or coverage["succeeded_runs"] != coverage["expected_units"] or
            any(coverage[field] for field in ("failed_runs", "cancelled_runs", "not_started_units"))):
        raise RuntimeError("Independent evaluation did not complete every expected Run and score; report is retained")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-core", help="Verify installed core against an explicit wheel and write its byte identity")
    freeze.add_argument("--wheel", required=True)
    freeze.add_argument("--output", required=True)
    data = commands.add_parser("prepare", help="Pinned GSM8K and native ChatTS public/private source preparation; CPU only")
    data.add_argument("--store", required=True)
    data.add_argument("--core-identity", required=True)
    data.add_argument("--output", required=True)
    data.add_argument("--gsm8k", required=True)
    data.add_argument("--chatts", required=True)
    data.add_argument("--python", default=sys.executable)
    data.add_argument("--train-per-source", type=int, default=4)
    data.add_argument("--eval-per-source", type=int, default=2)
    data.add_argument("--seed", type=int, default=7)
    for name in ("preflight", "train"):
        task = commands.add_parser(name)
        for option in ("store", "core-identity", "prepared", "output", "upstream", "model"):
            task.add_argument("--" + option, required=True)
        task.add_argument("--python", default=sys.executable)
        task.add_argument("--seed", type=int, default=7)
        task.add_argument("--group-size", type=int, default=4)
        task.add_argument("--max-model-requests", type=int, choices=range(8, 17), default=8,
                          help="Physical native HTTP segment limit per episode, including split tool markers")
        task.add_argument("--max-new-tokens", type=int, default=512)
        task.add_argument("--max-length", type=int, default=4096)
        task.add_argument("--episode-seconds", type=int, default=600)
        task.add_argument("--seconds", type=int, default=3600)
        task.add_argument("--learning-rate", type=float, default=0.00017)
        task.add_argument("--gpu-devices", type=int, nargs=2, default=[])
        task.add_argument("--gpu-uuids", nargs=2, default=[])
    publication = commands.add_parser("publish", help="Publish a saved native checkpoint with an explicit audited deployment dtype projection; no training")
    for option in ("store", "core-identity", "prepared", "training-parent", "native", "model", "output"):
        publication.add_argument("--" + option, required=True)
    publication.add_argument("--tokenizer-compatibility", choices=("native", "hf4"), default="native",
        help="Explicit deployment-only tokenizer metadata projection; original native assets are retained")
    evaluation = commands.add_parser("evaluate")
    for option in ("store", "core-identity", "prepared", "bundle", "model", "output"):
        evaluation.add_argument("--" + option, required=True)
    evaluation.add_argument("--device", default="cpu")
    evaluation.add_argument("--dtype", choices=("float32", "float16", "bfloat16"), default="float32")
    evaluation.add_argument("--seed", type=int, default=11)
    evaluation.add_argument("--max-new-tokens", type=int, default=512)
    score = commands.add_parser("rescore")
    for option in ("store", "core-identity", "report", "output"):
        score.add_argument("--" + option, required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze-core":
        frozen = freeze_core(args.wheel, args.output)
        result = {"verified_files": len(frozen["installed_files"]), "wheel_sha256": frozen["wheel_sha256"]}
    elif args.command == "prepare": result = prepare(args)
    elif args.command in ("preflight", "train"): result = train_or_preflight(args, args.command == "preflight")
    elif args.command == "publish": result = publish(args)
    elif args.command == "evaluate": result = evaluate(args)
    else: result = rescore(args)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
