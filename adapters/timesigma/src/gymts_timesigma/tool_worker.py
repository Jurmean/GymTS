"""Native catalog/domain bridge with no training or Evidence publication."""
import contextlib
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import time

from .scoring_worker import SOURCE_REVISION, _source


def execute(request):
    root = _source(request["source_repo"])
    import timesigma
    if root not in Path(timesigma.__file__).resolve().parents:
        raise ValueError("TimeSigma was imported outside the fixed source checkout")
    operation, arguments = request["operation"], request["arguments"]
    deadline, request_id = request["deadline_unix_ms"], request["request_id"]
    if operation == "model.catalog":
        from timesigma.algorithms import METHOD_CATALOG, EASYTSAD_REVISION, EASYTSAD_SCHEMAS
        values = METHOD_CATALOG.values() if isinstance(METHOD_CATALOG, dict) else METHOD_CATALOG
        return {"source_revision": SOURCE_REVISION, "easytsad_revision": EASYTSAD_REVISION,
                "schemas": list(EASYTSAD_SCHEMAS), "catalog": [asdict(item) for item in values],
                "adapter_execution_methods": ["AR", "IsolationForest"]}
    allowed = {"system.health", "capability.lookup", "memory.search", "memory.read", "memory.compare",
               "research.context", "experiment.preview", "recommendation.context"}
    if operation not in allowed:
        raise ValueError("Training and native Evidence mutation must use an admitted execution adapter")
    from timesigma.bridge.dispatch import dispatch_request
    from timesigma.bridge.protocol import ToolRequestEnvelope
    # Parsing the original envelope retains its exact version and scope checks.
    request = ToolRequestEnvelope.from_dict({"protocol_version": "timesigma.bridge.v1", "schema_version": 1,
        "request_id": request_id, "tool": operation, "deadline_unix_ms": deadline,
        "idempotency_key": request_id, "payload": arguments})
    if request.tool != operation:
        raise ValueError("Tool operation differs from its envelope")
    if request.deadline_unix_ms <= int(time.time() * 1000):
        raise ValueError("TimeSigma tool request has already expired")
    return dispatch_request(request)


def main():
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = execute(request)
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
