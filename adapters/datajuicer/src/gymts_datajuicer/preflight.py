"""Explicit optional native CPU checks, separate from lightweight contracts."""
import os
from pathlib import Path
import signal
import subprocess
from .common import loads, validate_source, write_json


def run_preflight(*, output, source, worker_python, upstream, model_path, model_identity, max_new_tokens=192):
    output, source = Path(output).absolute(), Path(source).absolute()
    output.mkdir(parents=True, exist_ok=False)
    public = loads((source / "public.json").read_text())
    validate_source(public["rows"])
    request = dict(public, upstream=str(Path(upstream).resolve()), model_path=str(Path(model_path).resolve()),
                   model_identity=model_identity, max_new_tokens=max_new_tokens)
    write_json(output / "request.json", request)
    allowed = ("PATH", "LD_LIBRARY_PATH", "TMPDIR", "LANG", "LC_ALL")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
               PYTHONDONTWRITEBYTECODE="1", TOKENIZERS_PARALLELISM="false",
               GYMTS_DATAJUICER_PARENT_PID=str(os.getpid()))
    for mode, flag in (("full-recipe", "--preflight"), ("filter-dedup", "--cpu-only")):
        argv = [str(Path(worker_python).absolute()), "-B", "-m", "gymts_datajuicer.worker", "--request",
                str(output / "request.json"), "--output", str(output / mode), flag]
        with (output / (mode + ".log")).open("wb") as stream:
            process = subprocess.Popen(argv, cwd=str(output), env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                status = process.wait(timeout=300)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
        if status != 0:
            raise RuntimeError("Native CPU preflight failed: " + mode + "; inspect " + str(output / (mode + ".log")))
    full = loads((output / "full-recipe/preflight.json").read_text())
    cpu = loads((output / "filter-dedup/response.json").read_text())
    summary = {"status": "passed", "full_qa_recipe": full["status"], "spawn_serialization": "passed",
        "model_loaded": False, "model_calls": 0, "gpu_visible": False,
        "stage_counts": [{"operator": stage["operator"], "input": len(stage["input"]),
                          "output": len(stage["output"])} for stage in cpu["stages"]],
        "upstream_tree_sha256": full["upstream"]["tree_sha256"]}
    write_json(output / "summary.json", summary)
    return summary
