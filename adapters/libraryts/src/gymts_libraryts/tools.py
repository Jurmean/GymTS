"""Independent tools persist CAS evidence; only real Runner calls carry Run IDs."""
import copy

from gymts.contracts import GymTSError, new_id, utc_now
from .runtime import LibraryTSRuntime
from .source import TOOLS, tool_ref

REQUEST = "gymts.libraryts/tool-request/1"
RESPONSE = "gymts.libraryts/tool-response/1"


class LibraryTSTools:
    def __init__(self, artifacts, implementation, *, timeout_seconds=120, traces=None, scope=None):
        # Legacy callers outside a Run retain the standalone catalog. Run-bound
        # capture always narrows the available tools, including implicit scope.
        scope = ("current_input" if traces is not None else "standalone") if scope is None else scope
        if scope not in ("current_input", "standalone"):
            raise GymTSError("invalid_config", "LibraryTS scope must be current_input or standalone")
        if traces is not None and scope == "standalone":
            raise GymTSError("permission_denied", "Run-bound LibraryTS tools cannot use standalone scope")
        self.artifacts = artifacts
        self.runtime = LibraryTSRuntime(implementation, timeout_seconds=timeout_seconds)
        self.traces = traces
        self.scope = scope
        self.last_call_ref = None

    def catalog(self):
        # Metadata inspection verifies source identities but imports no science.
        return [{"tool": name, **copy.deepcopy(description), "scope": self.scope,
                 "implementation": self.runtime.describe(name),
                 "dependency_status": "not_imported; verified only on invocation"}
                for name, description in TOOLS.items() if self.scope in description["allowed_scopes"]]

    def call(self, tool, arguments=None, params=None, *, parent_call_id=None):
        call_id, attempt_id, started = new_id("libraryts-call"), new_id("libraryts-attempt"), utc_now()
        arguments = {} if arguments is None else arguments
        params = {} if params is None else params
        request_ref = self.artifacts.save_json({"tool": tool, "arguments": arguments, "params": params,
            "implementation": self.runtime.implementation, "scope": self.scope,
            "effect": TOOLS.get(tool, {}).get("effect"), "started_at": started}, REQUEST)
        result_ref, output, error = None, None, None
        try:
            if tool in TOOLS and self.scope not in TOOLS[tool]["allowed_scopes"]:
                raise GymTSError("permission_denied", "LibraryTS tool is outside the current-input scope",
                                 stage="libraryts.scope")
            output = self.runtime.invoke(tool, arguments, params)
            result_ref = self.artifacts.save_json(output, RESPONSE)
        except Exception as failure:
            error = failure.to_dict() if isinstance(failure, GymTSError) else GymTSError(
                "execution_failure", "LibraryTS tool raised " + type(failure).__name__).to_dict()
            ended = utc_now()
            self.last_call_ref = self.artifacts.save_json({"call_id": call_id, "attempt_id": attempt_id,
                "status": "failed", "request_ref": request_ref, "started_at": started,
                "ended_at": ended, "error": error}, RESPONSE)
            if self.traces is not None and tool in TOOLS:
                self.traces.record_tool_call({"call_id": call_id, "attempt_id": attempt_id,
                    "parent_call_id": parent_call_id, "tool_ref": tool_ref(tool), "started_at": started,
                    "ended_at": ended, "status": "failed", "arguments_ref": request_ref,
                    "result_ref": None, "error": error, "environment_request_id": None, "operation_id": None})
            raise GymTSError(error["code"], error["message"], stage=error["stage"],
                links={"request_ref": request_ref, "failed_call_ref": self.last_call_ref}) from failure
        ended = utc_now()
        if self.traces is not None:
            self.traces.record_tool_call({"call_id": call_id, "attempt_id": attempt_id,
                "parent_call_id": parent_call_id, "tool_ref": tool_ref(tool), "started_at": started,
                "ended_at": ended, "status": "succeeded", "arguments_ref": request_ref,
                "result_ref": result_ref, "error": None, "environment_request_id": None, "operation_id": None})
        body = {"call_id": call_id, "attempt_id": attempt_id, "status": "succeeded", "tool": tool,
                "started_at": started, "ended_at": ended, "request_ref": request_ref,
                "response_ref": result_ref, "output": output}
        self.last_call_ref = self.artifacts.save_json(body, RESPONSE)
        return dict(body, call_ref=self.last_call_ref)
