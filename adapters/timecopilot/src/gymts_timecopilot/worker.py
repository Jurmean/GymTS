"""Native-only CPU worker; stdout is an acknowledged JSON-lines evidence channel."""
import contextlib
import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import traceback
import uuid

from .source import FORECASTERS, NATIVE_VERSION, PINNED_REVISION, checkout_identity, sha256

CHANNEL = sys.stdout
SEQUENCE = 0


def arm_parent_death():
    """Bind this isolated Linux worker and its group to the launching host."""
    expected = os.environ.get("GYMTS_TIMECOPILOT_PARENT_PID")
    if expected is None or not sys.platform.startswith("linux"):
        return
    expected = int(expected)
    if os.getpgrp() != os.getpid() or os.getsid(0) != os.getpid():
        raise RuntimeError("Parent-death cleanup requires an adapter-owned session")
    import ctypes
    import signal
    def stop_owned_group(signum, frame):
        os.killpg(os.getpid(), signal.SIGKILL)
    signal.signal(signal.SIGTERM, stop_owned_group)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot bind TimeCopilot worker lifetime to its host")
    # The launcher's explicit PID also covers death before this process arms prctl.
    if os.getppid() != expected:
        stop_owned_group(signal.SIGTERM, None)


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def identity(prefix):
    return prefix + "-" + uuid.uuid4().hex


def emit(kind, **fields):
    global SEQUENCE
    SEQUENCE += 1
    CHANNEL.write(json.dumps({"sequence": SEQUENCE, "kind": kind, **fields}, allow_nan=False) + "\n")
    CHANNEL.flush()
    ack = json.loads(sys.stdin.readline())
    if ack != {"ack": SEQUENCE}:
        raise RuntimeError("Host did not acknowledge persisted native evidence")


def native_identity(implementation):
    import timecopilot
    source = checkout_identity(implementation)
    installed = Path(timecopilot.__file__).resolve().parent
    if importlib.metadata.version("timecopilot") != NATIVE_VERSION:
        raise ValueError("Installed TimeCopilot has the wrong native version")
    loaded_files = {}
    for relative, expected in source["source_files_sha256"].items():
        path = installed.parent / relative
        if not path.is_file() or sha256(path) != expected:
            raise ValueError("Installed native source differs from fixed checkout: " + relative)
        loaded_files[relative] = {"path": str(path), "sha256": expected}
    versions = {name: importlib.metadata.version(name) for name in
                ("timecopilot", "foundationforecast", "pydantic-ai", "openai", "httpx", "statsforecast", "tsfeatures", "torch", "numpy", "pandas", "scipy")}
    return {"source": source, "installed_source_files": loaded_files, "dependencies": versions,
            "adapter_path": str(Path(__file__).resolve()), "adapter_sha256": sha256(__file__),
            "python": sys.version, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "tool_models": list(FORECASTERS), "llm_capture": "native_http_request_and_response_without_authorization_headers"}


def dataset():
    from statsforecast.utils import AirPassengers
    values = [float(x) for x in AirPassengers]
    if len(values) != 144:
        raise ValueError("Unexpected native AirPassengers fixture length")
    return {"dataset": "AirPassengers", "loader": "statsforecast.utils.AirPassengers",
            "dependency_version": importlib.metadata.version("statsforecast"),
            "start": "1949-01-01", "freq": "MS", "seasonality": 12,
            "values": values,
            "values_sha256": hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()}


class BudgetExceeded(RuntimeError):
    pass


def declared_tool_schema(schema, name, features, models):
    """Expose native parameter choices without changing native tool execution."""
    value = copy.deepcopy(schema)
    properties = value['properties']
    if name == 'tsfeatures_tool':
        properties['features']['items']['enum'] = sorted(features)
    elif name == 'cross_validation_tool':
        properties['models']['items']['enum'] = sorted(models)
    elif name in ('forecast_tool', 'detect_anomalies_tool'):
        properties['model']['enum'] = sorted(models)
    return value


def analyze(request):
    import httpx
    import pandas as pd
    from openai import AsyncOpenAI
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.toolsets.wrapper import WrapperToolset
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.profiles.openai import OpenAIModelProfile
    from timecopilot import TimeCopilot
    from timecopilot.models import stats
    from timecopilot.agent import TSFEATURES

    params, data = request["params"], request["input"]
    config, limits = params["model"], params["limits"]
    counts = {"model_requests": 0, "tool_calls": 0, "total_tokens": 0, "usage_missing_responses": 0}
    model_for_tool, invocations, returned_values, consumed_returns = {}, [], {}, {}
    last_model_call = None

    def budget(reason):
        emit("budget_exhausted", at=now(), reason=reason, counts=dict(counts), limits=limits)
        raise BudgetExceeded(reason)

    class CapturedTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.transport = httpx.AsyncHTTPTransport(retries=0)

        async def handle_async_request(self, http_request):
            nonlocal last_model_call
            if counts["model_requests"] >= limits["max_requests"]:
                budget("max_requests")
            if counts["total_tokens"] >= limits["max_total_tokens"]:
                budget("observed_total_tokens")
            body = json.loads((await http_request.aread()).decode())
            if body.get("stream"):
                raise ValueError("This IO profile requires native non-streaming model responses")
            call_id, attempt_id = identity("model"), identity("attempt")
            counts["model_requests"] += 1
            last_model_call = call_id
            emit("model_start", at=now(), call_id=call_id, attempt_id=attempt_id,
                 request={"method": http_request.method, "url": str(http_request.url),
                          "body": body, "headers": {"content-type": http_request.headers.get("content-type")},
                          "authorization_header_captured": False})
            end_emitted = False
            try:
                response = await self.transport.handle_async_request(http_request)
                raw = await response.aread()
                try:
                    output = json.loads(raw)
                except ValueError:
                    output = {"non_json_body": raw.decode(errors="replace")}
                usage = output.get("usage") if isinstance(output, dict) else None
                if usage and type(usage.get("total_tokens")) is int and usage["total_tokens"] >= 0:
                    counts["total_tokens"] += usage["total_tokens"]
                elif response.status_code < 400:
                    counts["usage_missing_responses"] += 1
                if isinstance(output, dict):
                    for choice in output.get("choices", []):
                        for call in choice.get("message", {}).get("tool_calls", []):
                            if call.get("id"):
                                model_for_tool[call["id"]] = call_id
                emit("model_end", at=now(), call_id=call_id, status="succeeded" if response.status_code < 400 else "failed",
                     response={"status_code": response.status_code, "body": output}, usage=usage,
                     **({"error": "Native model HTTP response " + str(response.status_code)} if response.status_code >= 400 else {}))
                end_emitted = True
                if response.status_code < 400:
                    for message in body.get("messages", []):
                        native_id = message.get("tool_call_id")
                        if message.get("role") == "tool" and native_id in returned_values:
                            if message.get("content") != returned_values[native_id]:
                                raise ValueError("Model request altered a captured native tool return")
                            consumed_returns.setdefault(native_id, []).append(call_id)
                if counts["usage_missing_responses"]:
                    budget("provider_usage_missing; total token accounting cannot be verified")
                if counts["total_tokens"] > limits["max_total_tokens"]:
                    budget("observed_total_tokens; response preserved, no further request dispatched")
                return response
            except BudgetExceeded:
                raise
            except Exception as error:
                if not end_emitted:
                    emit("model_end", at=now(), call_id=call_id, status="failed",
                         error=type(error).__name__ + ": " + str(error))
                raise

        async def aclose(self):
            await self.transport.aclose()

    class CapturedToolset(WrapperToolset):
        async def get_tools(self, ctx):
            tools = await self.wrapped.get_tools(ctx)
            return {name: replace(tool, tool_def=replace(tool.tool_def,
                parameters_json_schema=declared_tool_schema(tool.tool_def.parameters_json_schema,
                    name, TSFEATURES, available_models))) for name, tool in tools.items()}

        async def call_tool(self, name, tool_args, ctx, tool):
            if counts["tool_calls"] >= limits["max_tool_calls"]:
                budget("max_tool_calls")
            call_id, attempt_id = identity("tool"), identity("attempt")
            counts["tool_calls"] += 1
            native_id = getattr(ctx, "tool_call_id", None)
            invocation = {"tool": name, "arguments": tool_args, "native_tool_call_id": native_id}
            emit("tool_start", at=now(), call_id=call_id, attempt_id=attempt_id, tool=name,
                 parent_call_id=model_for_tool.get(native_id, last_model_call), request=invocation)
            try:
                value = await self.wrapped.call_tool(name, tool_args, ctx, tool)
                emit("tool_end", at=now(), call_id=call_id, status="succeeded", response={"return_value": value})
                returned_values[native_id] = value
                invocations.append({**invocation, "status": "succeeded"})
                return value
            except Exception as error:
                emit("tool_end", at=now(), call_id=call_id, status="failed",
                     error=type(error).__name__ + ": " + str(error))
                invocations.append({**invocation, "status": "failed"})
                raise

    names = params.get("forecasters", list(FORECASTERS))
    forecasters = [getattr(stats, name)() for name in names]
    key_name = config.get("credential_env")
    key = os.environ[key_name] if key_name else "local-no-secret"
    client = AsyncOpenAI(base_url=config["base_url"], api_key=key, max_retries=0,
        timeout=limits["max_wall_time_s"], http_client=httpx.AsyncClient(transport=CapturedTransport(),
            timeout=limits["max_wall_time_s"]))
    tool_choice_mode = config.get('tool_choice_mode', 'required')
    llm = OpenAIModel(config["name"], provider=OpenAIProvider(openai_client=client),
        profile=OpenAIModelProfile(openai_supports_tool_choice_required=tool_choice_mode == 'required'))
    copilot = TimeCopilot(llm=llm, forecasters=forecasters,
        retries=params.get("retries", 2), model_settings={"temperature": params.get("temperature", 0),
            "max_tokens": limits["max_response_tokens"], "parallel_tool_calls": False})
    available_models = list(copilot.forecasters)
    context = data["context"]
    values = data["series"][0]["values"]
    df = pd.DataFrame({"unique_id": ["authorized-history"] * len(values),
        "ds": pd.date_range(context["start"], periods=len(values), freq=context["freq"]), "y": values})
    # Public API only: retain native closures and native validation; merely wrap invocation.
    native_toolsets = list(copilot.forecasting_agent.toolsets)
    with copilot.forecasting_agent.override(tools=[], toolsets=[CapturedToolset(item) for item in native_toolsets]):
        result = copilot.analyze(df=df, h=context["horizon"], freq=context["freq"],
                                 seasonality=context["seasonality"], query=None)
    analysis = result.output.model_dump(mode="json")
    selected = analysis["selected_model"]
    required = {"tsfeatures_tool", "cross_validation_tool", "forecast_tool", "detect_anomalies_tool"}
    if not required.issubset({row["tool"] for row in invocations if row["status"] == "succeeded"}):
        raise ValueError("Native Agent completed without all four required successful tool stages")
    if any(not row["native_tool_call_id"] or row["native_tool_call_id"] not in consumed_returns
           for row in invocations if row["status"] == "succeeded"):
        raise ValueError("Native tool result was not consumed unchanged by a later successful model request")
    comparisons = [row for row in invocations if row["tool"] == "cross_validation_tool" and row["status"] == "succeeded"]
    if not any(len(set(row["arguments"]["models"])) >= 2 and "SeasonalNaive" in row["arguments"]["models"] for row in comparisons):
        raise ValueError("Native Agent did not compare multiple models including its seasonal baseline")
    forecasts = [row for row in invocations if row["tool"] == "forecast_tool" and row["status"] == "succeeded"]
    anomalies = [row for row in invocations if row["tool"] == "detect_anomalies_tool" and row["status"] == "succeeded"]
    if forecasts[-1]["arguments"]["model"] != selected or anomalies[-1]["arguments"]["model"] != selected:
        raise ValueError("Native final selection differs from executed forecast or anomaly model")
    if result.fcst_df is None or selected not in result.fcst_df:
        raise ValueError("Native Agent produced no forecast for its selected model")
    expected_dates = pd.date_range(df["ds"].iloc[-1], periods=context["horizon"] + 1, freq=context["freq"])[1:]
    if pd.to_datetime(result.fcst_df["ds"]).tolist() != expected_dates.tolist():
        raise ValueError("Native forecast dates do not match the requested future horizon")
    frames = {name: json.loads(frame.to_json(orient="split", date_format="iso")) if frame is not None else None
              for name, frame in (("forecast", result.fcst_df), ("cross_validation", result.eval_df),
                                  ("features", result.features_df), ("anomalies", result.anomalies_df))}
    return {"forecast": [float(x) for x in result.fcst_df[selected]], "analysis": analysis,
        "native_frames": frames, "frame_serialization": "pandas split JSON; native NaN becomes null",
        "native_messages": json.loads(result.all_messages_json()), "tool_invocations": invocations,
        "native_tool_return_consumption": consumed_returns,
        "budget": {"counts": counts, "limits": limits, "termination": "native_final_result",
            "token_limit_semantics": "observed provider total; a completed response can cross the limit; then stop before consumption or further dispatch"},
        "native_identity": native_identity(request["implementation"]),
        "tool_schema_adaptation": {"kind": "native_parameter_enumerations", "features": sorted(TSFEATURES),
            "available_models": sorted(available_models), "native_implementations_unchanged": True},
        'provider_request_policy': {'tool_choice_mode':tool_choice_mode,
            'mapping':'PydanticAI OpenAIModelProfile.openai_supports_tool_choice_required',
            'native_output_validation_unchanged':True},
        "input_sha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()}


def main():
    arm_parent_death()
    request = json.loads(sys.stdin.readline())
    try:
        with contextlib.redirect_stdout(sys.stderr):
            mode = request["mode"]
            if mode == "identity":
                result = native_identity(request["implementation"])
            elif mode == "dataset":
                result = dataset()
            elif mode == "analyze":
                result = analyze(request)
            else:
                raise ValueError("Unsupported TimeCopilot worker mode")
        emit("terminal", at=now(), status="succeeded", result=result)
        return 0
    except Exception as error:
        # No environment values, auth headers or raw exception response objects are serialized.
        emit("terminal", at=now(), status="failed", error={"type": type(error).__name__, "message": str(error)})
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
