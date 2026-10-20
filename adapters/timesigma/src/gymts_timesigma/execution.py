"""Deadline-bound scientific execution using native Runs and durable receipts.

The host worker shares the caller's store, starts a separate process group,
and grants the scientific subprocesses no provider credentials. A receipt is
published after each successful public ``records.begin_run`` and before that
call returns to the Runner. Importing historical evidence is never involved.
"""
import contextlib
import copy
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from uuid import uuid4

from gymts.contracts import GymTSError, canonical_json, utc_now


RECEIPT_SCHEMA = "gymts.timesigma/execution-receipt/1"
_CLEANUP_SECONDS = 1.0
_TERMINATED = False


def _directory_sync(path):
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _make_directory(path):
    missing, current = [], Path(path)
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _directory_sync(directory.parent)


def _receipt_path(gym):
    directory = Path(gym.root).resolve() / "timesigma" / "executions" / uuid4().hex
    _make_directory(directory)
    return directory / "receipt.json"


def _write_receipt(path, value):
    """Publish a complete local receipt, including its directory entry."""
    path = Path(path)
    _make_directory(path.parent)
    temporary = path.with_name(".receipt-" + uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _directory_sync(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read_receipt(path):
    value = json.loads(Path(path).read_bytes())
    if (not isinstance(value, dict) or value.get("schema_version") != RECEIPT_SCHEMA
            or not isinstance(value.get("run_ids"), list)
            or any(not isinstance(item, str) or not item for item in value["run_ids"])
            or len(value["run_ids"]) != len(set(value["run_ids"]))):
        raise GymTSError("artifact_integrity", "Execution receipt has an invalid native Run list")
    return value


def _new_receipt(path, *, deadline_unix_ms=None):
    value = {"schema_version": RECEIPT_SCHEMA, "execution_id": Path(path).parent.name,
        "created_at": utc_now(), "updated_at": utc_now(), "phase": "created",
        "actual_phase": "worker_start", "run_ids": [], "deadline_unix_ms": deadline_unix_ms}
    _write_receipt(path, value)
    return value


def _native_evidence(gym, receipt, *, phase, actual_phase):
    """Snapshot only real records. A killed worker may leave an unsealed prefix."""
    value = copy.deepcopy(receipt)
    value.update(updated_at=utc_now(), phase=phase, actual_phase=actual_phase)
    states = []
    for run_id in value["run_ids"]:
        run = gym.records.get_run(run_id)
        events = run["events"]
        states.append({"run_id": run_id, "status": run["result"]["status"] if run["result"] else "running",
            "last_event_kind": events[-1]["kind"] if events else None,
            "through_seq": events[-1]["seq"] if events else 0,
            "result_ref": run["result_ref"], "trace_ref": run["execution_snapshot_ref"]})
    snapshot = gym.records.snapshot(value["run_ids"], {"outcomes_as_of": utc_now()})
    value.update(run_states=states, record_snapshot_ref=snapshot["snapshot_ref"])
    reference = gym.artifacts.save_json(value, RECEIPT_SCHEMA)
    return value, {"run_ids": list(value["run_ids"]), "record_snapshot_ref": snapshot["snapshot_ref"],
        "execution_receipt_ref": reference, "phase": phase, "actual_phase": actual_phase,
        "run_states": states}


def _error(error, links):
    if isinstance(error, GymTSError):
        info = error.to_dict()
        return GymTSError(info["code"], info["message"], stage=info["stage"], method=info["method"],
            run_id=info["run_id"] or next(iter(links["run_ids"]), None),
            links=dict(info["links"], **links), retryable=info["retryable"], side_effect=info["side_effect"])
    return GymTSError("execution_failure", "Scientific execution raised " + type(error).__name__,
        stage="execution", run_id=next(iter(links["run_ids"]), None), links=links,
        side_effect="possible" if links["run_ids"] else "none")


def _uncaptured(phase, actual_phase):
    return {"run_ids": [], "record_snapshot_ref": None, "execution_receipt_ref": None,
            "phase": phase, "actual_phase": actual_phase}


def capture_runs(gym, operation, *, receipt_path=None):
    """Execute a zero-argument callable and capture its genuinely allocated Runs.

    The result is ``{result, run_ids, record_snapshot_ref, execution_receipt_ref,
    phase, actual_phase, run_states}``. Failures carry the same evidence in
    ``GymTSError.links``. The public begin_run method is restored on every path.
    This helper is synchronous; callers must not share its records object with
    another concurrent operation.
    """
    try:
        path = Path(receipt_path) if receipt_path is not None else _receipt_path(gym)
        receipt = _read_receipt(path) if path.exists() else _new_receipt(path)
        receipt.update(phase="operation_started", actual_phase="operation", worker_pid=os.getpid())
        _write_receipt(path, receipt)
    except (OSError, GymTSError, ValueError) as error:
        raise GymTSError("recording_failure", "Execution receipt could not be initialized", stage="execution.receipt",
            links=_uncaptured("not_started", "receipt_start")) from error
    original = gym.records.begin_run
    had_override = "begin_run" in vars(gym.records)
    previous_override = vars(gym.records).get("begin_run")

    def begin_run(*args, **kwargs):
        # Defer SIGTERM across the small allocation/receipt critical section.
        # The signal is delivered immediately after the durable receipt exists.
        if _TERMINATED:
            raise GymTSError("deadline_exceeded", "Scientific execution was terminated", stage="execution.deadline")
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            allocated = original(*args, **kwargs)
            run_id = allocated["run_id"]
            if run_id not in receipt["run_ids"]:
                receipt["run_ids"].append(run_id)
            receipt.update(updated_at=utc_now(), phase="run_allocated", actual_phase="native_run")
            try:
                _write_receipt(path, receipt)
            except (OSError, GymTSError) as error:
                raise GymTSError("recording_failure", "Native Run allocation could not be durably receipted",
                    stage="execution.receipt", run_id=run_id, links={"run_ids": list(receipt["run_ids"])}) from error
            return allocated
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    gym.records.begin_run = begin_run
    try:
        result = operation()
        canonical_json(result)
    except BaseException as error:
        actual_phase = getattr(error, "stage", "operation")
        links = None
        try:
            receipt, links = _native_evidence(gym, receipt, phase="failed", actual_phase=actual_phase)
            _write_receipt(path, receipt)
        except BaseException as capture_error:
            links = links or dict(_uncaptured("capture_failed", actual_phase), run_ids=list(receipt["run_ids"]))
            links.update(phase="capture_failed", capture_error_type=type(capture_error).__name__)
        raise _error(error, links) from error
    else:
        links = None
        try:
            receipt, links = _native_evidence(gym, receipt, phase="completed", actual_phase="completed")
            _write_receipt(path, receipt)
        except BaseException as error:
            links = links or dict(_uncaptured("capture_failed", "final_capture"), run_ids=list(receipt["run_ids"]))
            links.update(phase="capture_failed", actual_phase="final_capture")
            raise _error(error, links) from error
        return dict(links, result=result)
    finally:
        if had_override:
            gym.records.begin_run = previous_override
        else:
            del gym.records.begin_run


def _worker_command():
    return [sys.executable, "-B", "-m", "gymts_timesigma.execution", "--worker"]


def _worker_environment():
    environment = {key: value for key, value in os.environ.items()
        if not re.search(r"api.?key|token|secret|password|authorization|credential|provider|(?:^|_)llm(?:_|$)|(?:^|_)openai(?:_|$)", key, re.I)}
    environment.pop("PYTHONPATH", None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1", CUDA_VISIBLE_DEVICES="")
    return environment


def _stop_group(process):
    """Give the Runner time to seal, then kill every surviving descendant."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        output = process.communicate(timeout=_CLEANUP_SECONDS)
    except subprocess.TimeoutExpired:
        output = None
    finally:
        # A worker can exit before a scientific grandchild that ignored TERM.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if output is None:
        try:
            output = process.communicate(timeout=.5)
        except subprocess.TimeoutExpired:
            # SIGKILL is already pending even if an OS IO wait delays reaping.
            output = (b"", b"")
    return output


def _parent_links(gym, path, *, phase, actual_phase):
    receipt = _read_receipt(path)
    links = None
    try:
        receipt, links = _native_evidence(gym, receipt, phase=phase, actual_phase=actual_phase)
        _write_receipt(path, receipt)
        return links
    except (OSError, GymTSError) as error:
        links = links or {"run_ids": list(receipt["run_ids"]), "record_snapshot_ref": receipt.get("record_snapshot_ref"),
            "execution_receipt_ref": None, "actual_phase": actual_phase}
        return dict(links, phase="capture_failed", capture_error_type=type(error).__name__)


def run_with_deadline(gym, arguments, *, deadline_unix_ms):
    """Run an experiment or an exclusive score_spec under a hard deadline.

    ``{score_spec: ...}`` calls native AutoBenchTS.score on existing Runs. The
    ordinary imported/params experiment mode retains its original interface.
    """
    if (type(deadline_unix_ms) is not int or not 0 < deadline_unix_ms <= 2**53 - 1
            or not isinstance(arguments, dict)):
        raise GymTSError("invalid_request", "Execution requires object arguments and an absolute integer deadline")
    score_mode = set(arguments) == {"score_spec"} and isinstance(arguments["score_spec"], dict)
    experiment_mode = (not set(arguments) - {"params", "imported", "artifact", "metrics"}
        and isinstance(arguments.get("params"), dict) and isinstance(arguments.get("imported"), dict))
    if not (score_mode or experiment_mode):
        raise GymTSError("invalid_request", "Use either imported/params or an exclusive score_spec object")
    try:
        canonical_json(arguments)
    except (TypeError, ValueError) as error:
        raise GymTSError("invalid_request", "Execution arguments must be finite JSON") from error
    if deadline_unix_ms <= time.time() * 1000:
        raise GymTSError("deadline_exceeded", "Scientific execution deadline has expired", stage="execution.deadline",
            links={"run_ids": [], "record_snapshot_ref": None, "execution_receipt_ref": None,
                   "phase": "not_started", "actual_phase": "worker_start"})
    try:
        path = _receipt_path(gym)
        _new_receipt(path, deadline_unix_ms=deadline_unix_ms)
    except (OSError, GymTSError) as error:
        raise GymTSError("recording_failure", "Execution receipt could not be initialized", stage="execution.receipt",
            links=_uncaptured("not_started", "receipt_start")) from error
    request = {"store": str(Path(gym.root).resolve()), "arguments": arguments,
               "receipt_path": str(path), "deadline_unix_ms": deadline_unix_ms}
    process = None
    try:
        process = subprocess.Popen(_worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=_worker_environment(), cwd=str(path.parent), start_new_session=True)
        remaining = max(.001, deadline_unix_ms / 1000 - time.time())
        output, _ = process.communicate(canonical_json(request), timeout=remaining)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        if process is not None:
            _stop_group(process)
        interrupted = isinstance(error, KeyboardInterrupt)
        links = _parent_links(gym, path, phase="cancelled" if interrupted else "deadline_exceeded",
                              actual_phase="execution.cancel" if interrupted else "execution.deadline")
        raise GymTSError("cancelled" if interrupted else "deadline_exceeded",
            "Scientific execution was interrupted" if interrupted else "Scientific execution exceeded its hard deadline",
            stage="execution", run_id=next(iter(links["run_ids"]), None), links=links,
            side_effect="possible" if links["run_ids"] else "none") from error
    except OSError as error:
        if process is not None:
            _stop_group(process)
        links = _parent_links(gym, path, phase="worker_start_failed", actual_phase="worker_start")
        raise GymTSError("unsupported_capability", "Scientific host worker could not start", stage="execution", links=links) from error
    # The direct worker has exited. Its group must not leave an orphaned native
    # process running after a protocol failure or an abruptly exited host.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        response = json.loads(output, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if (not isinstance(response, dict) or type(response.get("ok")) is not bool
                or response["ok"] and "result" not in response
                or not response["ok"] and not isinstance(response.get("error"), dict)):
            raise ValueError("Missing worker envelope")
    except (ValueError, UnicodeError) as error:
        links = _parent_links(gym, path, phase="worker_protocol_failed", actual_phase="worker_response")
        raise GymTSError("execution_failure", "Scientific host worker returned an invalid response", stage="execution", links=links) from error
    if not response["ok"] or process.returncode:
        info = response.get("error") or {}
        links = dict(info.get("links", {}))
        links.update(_parent_links(gym, path, phase="failed", actual_phase=info.get("stage", "worker_exit")))
        raise GymTSError(info.get("code", "execution_failure"), info.get("message", "Scientific host worker failed"),
            stage=info.get("stage", "execution"), run_id=info.get("run_id") or next(iter(links["run_ids"]), None),
            links=links, side_effect="possible" if links["run_ids"] else "none")
    if deadline_unix_ms <= time.time() * 1000:
        links = _parent_links(gym, path, phase="deadline_exceeded", actual_phase="worker_response")
        raise GymTSError("deadline_exceeded", "Scientific execution completed after its deadline", stage="execution", links=links)
    return response["result"]


def _worker_main(operation=None):
    global _TERMINATED
    _TERMINATED = False

    def terminate(signum, frame):
        global _TERMINATED
        if not _TERMINATED:
            _TERMINATED = True
            raise GymTSError("deadline_exceeded", "Scientific worker received termination", stage="execution.deadline")

    signal.signal(signal.SIGTERM, terminate)
    try:
        request = json.load(sys.stdin)
        from gymts import GymTS
        from .pipeline import run_experiment
        with GymTS(request["store"], integrations=("timesigma",)) as gym:
            def execute():
                if request["deadline_unix_ms"] <= time.time() * 1000:
                    raise GymTSError("deadline_exceeded", "Scientific worker started after its deadline", stage="execution.deadline")
                arguments = request["arguments"]
                if operation is not None:
                    result = operation(gym, arguments)
                elif "score_spec" in arguments:
                    result = gym.autobench.score(arguments["score_spec"])
                else:
                    result = run_experiment(gym, arguments["imported"], arguments["params"],
                        artifact=arguments.get("artifact"), metrics=arguments.get("metrics"))
                if _TERMINATED:
                    raise GymTSError("deadline_exceeded", "Scientific worker was terminated during execution", stage="execution.deadline")
                return result
            with open(os.devnull, "w") as discarded, contextlib.redirect_stdout(discarded):
                captured = capture_runs(gym, execute, receipt_path=request["receipt_path"])
            response = {"ok": True, "result": captured["result"]}
    except BaseException as error:
        response = {"ok": False, "error": error.to_dict() if isinstance(error, GymTSError) else
            GymTSError("execution_failure", "Scientific host worker raised " + type(error).__name__, stage="execution").to_dict()}
    sys.stdout.buffer.write(canonical_json(response) + b"\n")
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("This module is an internal scientific execution worker")
    raise SystemExit(_worker_main())
