"""Native ChatTS wire adaptation and a separately identified signal baseline."""
import copy
import json
import math
import re
import statistics

from gymts.contracts import canonical_json, utc_now
from gymts.http_candidate import FrozenJSONHTTPCandidate
from gymts.plugin_support import fail as _fail, payload
from .qa_contract import (DIALECTS, INPUT, OUTPUT, PLACEHOLDER, PROTOCOL,
                          TASK_IDS, load_qa_input)


# Compatibility for existing offline adapter audits; new adapters use qa_contract.
_model_input = load_qa_input


class ChatTSHTTPCandidate(FrozenJSONHTTPCandidate):
    """Native ChatTS wire codec on the shared frozen HTTP lifecycle."""

    DEFAULTS = {"dialect": "chatts-timeseries/v1", "timeout_seconds": 120.0,
                "max_tokens": 512, "temperature": 0.0, "top_p": 1.0,
                "api_key_env": None, "expected_system_fingerprint": None,
                "enable_thinking": None, "json_object": False}
    DIALECTS = DIALECTS
    SEED_DIALECTS = ("chatts-vllm-text-envelope/v1",)
    KIND = "chatts_http"
    NORMALIZATION = "backend_processor"
    REVISION_PROVENANCE = "configured"
    TASK_PROTOCOL_REF = PROTOCOL
    OUTPUT_SCHEMA_REF = OUTPUT

    def _load_input(self, task_input):
        return load_qa_input(task_input, self.resources)

    def _request_metadata(self, model_input):
        return {"native_timeseries": model_input["timeseries"],
                "series_names": model_input["series_names"]}

    def _validate_controls(self):
        if self.params["enable_thinking"] is not None and type(self.params["enable_thinking"]) is not bool:
            _fail("invalid_config", "enable_thinking must be a boolean or null", "configure")
        if type(self.params["json_object"]) is not bool:
            _fail("invalid_config", "json_object must be a boolean", "configure")
        if self.params["dialect"] != DIALECTS[1] and (self.params["enable_thinking"] is not None or self.params["json_object"]):
            _fail("invalid_config", "Thinking/JSON controls require the ChatTS vLLM text-envelope dialect", "configure")

    def _wire(self, model_input):
        messages = copy.deepcopy(model_input["messages"])
        wire = {"model": self.model, "messages": messages,
                "temperature": self.params["temperature"], "top_p": self.params["top_p"],
                "max_tokens": self.params["max_tokens"], "stream": False}
        if self.params["dialect"] == DIALECTS[0]:
            wire["timeseries"] = copy.deepcopy(model_input["timeseries"])
            return wire
        count = sum(message["content"].count(PLACEHOLDER) for message in messages)
        if count == 0:
            # Match the existing Bench compatibility shim's native modality
            # envelope for prompts that have not injected TS placeholders.
            parts = [{"type": "text", "text": messages[-1]["content"]}]
            for name, values in zip(model_input["series_names"], model_input["timeseries"]):
                parts.append({"type": "text", "text": "\nAttached time series " + name + ": " + PLACEHOLDER})
                parts.append({"type": "text", "text": "chatts-timeseries:v1:" + json.dumps(
                    values, allow_nan=False, separators=(",", ":"))})
            messages[-1]["content"] = parts
        # Put each envelope immediately after its EXISTING placeholder. No extra
        # placeholders and no ordinary-text substitute for the native payload.
        index = 0
        for message in messages if count else []:
            chunks = message["content"].split(PLACEHOLDER)
            if len(chunks) == 1:
                continue
            parts = []
            for chunk in chunks[:-1]:
                parts.append({"type": "text", "text": chunk + PLACEHOLDER})
                parts.append({"type": "text", "text": "chatts-timeseries:v1:" + json.dumps(
                    model_input["timeseries"][index], allow_nan=False, separators=(",", ":"))})
                index += 1
            if chunks[-1]:
                parts.append({"type": "text", "text": chunks[-1]})
            message["content"] = parts
        if self.params["enable_thinking"] is not None:
            wire["chat_template_kwargs"] = {"enable_thinking": self.params["enable_thinking"]}
        if self.params["json_object"]:
            wire["response_format"] = {"type": "json_object"}
        return wire


def _variance(values):
    mean = statistics.fmean(values)
    return statistics.fmean((value - mean) ** 2 for value in values)


def _line(values):
    n = len(values)
    center = (n - 1) / 2
    mean = statistics.fmean(values)
    denominator = sum((i - center) ** 2 for i in range(n))
    slope = sum((i - center) * (value - mean) for i, value in enumerate(values)) / denominator if denominator else 0.0
    intercept = mean - slope * center
    return slope, intercept, [value - (intercept + slope * i) for i, value in enumerate(values)]


def _corr(left, right):
    if len(left) < 3 or len(left) != len(right):
        return 0.0
    a, b = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((x - a) * (y - b) for x, y in zip(left, right))
    denominator = math.sqrt(sum((x - a) ** 2 for x in left) * sum((y - b) ** 2 for y in right))
    return numerator / denominator if denominator > 1e-20 else 0.0


def _normalize(values, size=96):
    if len(values) > size:
        values = [values[round(i * (len(values) - 1) / (size - 1))] for i in range(size)]
    mean = statistics.fmean(values)
    scale = math.sqrt(_variance(values)) or 1.0
    return [(value - mean) / scale for value in values]


def _dtw(left, right):
    previous = [0.0] + [float("inf")] * len(right)
    for x in left:
        current = [float("inf")]
        for j, y in enumerate(right):
            current.append((x - y) ** 2 + min(current[-1], previous[j], previous[j + 1]))
        previous = current
    return previous[-1] / (len(left) + len(right))


class ChatTSSignalBaseline:
    """Dependency-free numerical heuristics, not a ChatTS model or an oracle."""

    REVISION = "chatts-signal-baseline/1.0.0"

    @staticmethod
    def check_compatibility_spec(context):
        experiment = context["experiment"]
        if experiment["candidate"]["params"]["task_id"] != experiment["scene"]["task"]["params"].get("task_id"):
            _fail("unsupported_capability", "Configured signal baseline task differs from the Task")

    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)
        if set(spec["params"]) != {"task_id"} or spec["params"]["task_id"] not in TASK_IDS:
            _fail("invalid_config", "Signal baseline requires one supported task_id", "configure")
        self.task_id, self.state = spec["params"]["task_id"], "created"

    def prepare(self, context, training):
        if self.state != "created":
            _fail("invalid_state", "Candidate prepare may be called only once", "prepare")
        if training is not None or context["learning"]["prepare"] != "load_only" or context["learning"]["online"] != "frozen":
            _fail("unsupported_capability", "Signal baseline supports frozen load_only inference", "prepare")
        if self.spec.get("artifact") is not None or self.spec.get("inherited_state"):
            _fail("unsupported_capability", "Signal baseline has no inherited state", "prepare")
        self.resources, self.state = context["resources"], "prepared"
        return {"model_revision": self.REVISION, "state_refs": [], "training_provenance_ref": None}

    def _predict(self, model_input):
        # Deliberately inspect only the public model input. No labels, generator
        # parameters, private metadata, evaluation data or source files are read.
        # Source profiles publish display labels ("Series X", "Candidate A").
        # Canonicalize only these public labels for algorithm lookup; the HTTP
        # payload and original ordering remain untouched.
        names = [re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") for name in model_input["series_names"]]
        series = dict(zip(names, model_input["timeseries"]))
        values = model_input["timeseries"][0]
        n = len(values)
        if self.task_id == "pattern.trend_direction":
            slope, _, residuals = _line(values)
            change = slope * max(n - 1, 1)
            threshold = .75 * math.sqrt(_variance(residuals)) + 1e-9
            return {"trend_direction": "increasing" if change > threshold else "decreasing" if change < -threshold else "stable"}
        if self.task_id == "anomaly.point_indices":
            residuals = [value - statistics.median(values[max(0, i - 5):min(n, i + 6)]) for i, value in enumerate(values)]
            center = statistics.median(residuals)
            mad = statistics.median(abs(value - center) for value in residuals)
            threshold = max(6 * 1.4826 * mad, 1e-7)
            return {"indices": [i for i, value in enumerate(residuals) if abs(value - center) > threshold]}
        if self.task_id == "forecast.numeric":
            context = model_input.get("context") or {}
            horizon = context.get("horizon", context.get("forecast_horizon"))
            if horizon is None:
                schema = model_input.get("output_schema", {}).get("properties", {}).get("forecast", {})
                horizon = schema.get("maxItems")
            if horizon is None:
                match = re.search(r"next\s+(\d+)\s+(?:values|points|steps)", " ".join(m["content"] for m in model_input["messages"]), re.I)
                horizon = int(match[1]) if match else None
            if type(horizon) is not int or not 1 <= horizon <= 10000:
                _fail("schema_mismatch", "Forecast baseline needs an explicit public positive horizon", "infer")
            tail = values[-min(32, n):]
            slope, intercept, _ = _line(tail)
            return {"forecast": [intercept + slope * (len(tail) + i) for i in range(horizon)]}
        if self.task_id == "process.stationarity_type":
            slope, _, residuals = _line(values)
            residual_scale = math.sqrt(_variance(residuals)) + 1e-9
            first, last = residuals[:max(2, n // 3)], residuals[-max(2, n // 3):]
            low, high = sorted((_variance(first) + 1e-10, _variance(last) + 1e-10))
            change = abs(slope * max(n - 1, 1))
            if high / low > 4:
                result = "variance_regime"
            elif change > 3 * residual_scale:
                result = "deterministic_trend"
            elif _corr(residuals[:-1], residuals[1:]) > .8:
                result = "unit_root"
            else:
                result = "stationary"
            return {"type": result}
        if self.task_id == "relation.lagged_dependence":
            x, y = series.get("series_x"), series.get("series_y")
            if x is None or y is None or len(x) != len(y):
                _fail("schema_mismatch", "Lag baseline requires equal-length series_x and series_y", "infer")
            x = [b - a for a, b in zip(x, x[1:])]
            y = [b - a for a, b in zip(y, y[1:])]
            scores = [(abs(_corr(x[:-lag], y[lag:])), "x_to_y", lag) for lag in range(1, min(16, len(x) - 3) + 1)]
            scores += [(abs(_corr(y[:-lag], x[lag:])), "y_to_x", lag) for lag in range(1, min(16, len(x) - 3) + 1)]
            score, direction, lag = max(scores, default=(0.0, "neither", 0))
            return {"direction": direction, "lag": lag} if score > .45 else {"direction": "neither", "lag": 0}
        if self.task_id == "similarity.shape_retrieval":
            query = _normalize(series.get("query", values))
            candidates = [(name, candidate) for name, candidate in series.items() if name.startswith("candidate_")]
            if not candidates:
                _fail("schema_mismatch", "Shape baseline needs named candidate series", "infer")
            return {"candidate_id": min(candidates, key=lambda item: _dtw(query, _normalize(item[1])))[0]}
        if self.task_id == "pattern.seasonality_profile":
            _, _, detrended = _line(values)
            sample = detrended if n <= 256 else [detrended[round(i * (n - 1) / 255)] for i in range(256)]
            length = len(sample)
            powers = []
            for k in range(2, max(3, length // 2)):
                real = sum(value * math.cos(2 * math.pi * k * i / length) for i, value in enumerate(sample))
                imag = sum(value * math.sin(2 * math.pi * k * i / length) for i, value in enumerate(sample))
                powers.append((real * real + imag * imag, k))
            total = sum(power for power, _ in powers) or 1.0
            peaks = []
            for power, k in sorted(powers, reverse=True):
                if power / total < .12:
                    break
                if any(abs(k - other) <= 1 or abs(k / other - round(k / other)) < .12 for other in peaks):
                    continue
                peaks.append(k)
            return {"profile": "none" if not peaks else "single_period" if len(peaks) == 1 else "multiple_periods"}
        _fail("unsupported_capability", "Unsupported baseline task", "infer")

    def infer(self, task_input):
        if self.state != "prepared":
            _fail("invalid_state", "Candidate infer requires prepared state", "infer")
        model_input = load_qa_input(task_input, self.resources)
        answer = self._predict(model_input)
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
                "produced_at": utc_now(), "model_revision": self.REVISION,
                "payload": payload(OUTPUT, {"raw_text": canonical_json(answer).decode("utf-8"),
                    "evidence": {"kind": "signal_algorithm_baseline", "algorithm_revision": self.REVISION,
                                 "task_id": self.task_id, "gold_access": False}})}

    def update(self, feedback):
        _fail("unsupported_capability", "Signal baseline does not update online", "update")

    def finish(self):
        self.state = "closed"
        return []
