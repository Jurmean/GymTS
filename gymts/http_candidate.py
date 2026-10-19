"""Public frozen JSON-over-HTTP Candidate support for explicit model adapters.

The transport has no task or model integration dependency. Concrete adapters
provide task decoding and wire encoding; requests are captured and never retried.
"""
import copy
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from gymts.contracts import canonical_json, utc_now
from gymts.plugin_support import fail as _fail, payload


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_config", name + " must be a nonempty string", "configure")
    return value.strip()


def _number(value, name, minimum, maximum=None, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or value < minimum
            or (maximum is not None and value > maximum)
            or (integer and type(value) is not int)):
        _fail("invalid_config", "Invalid " + name, "configure")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FrozenJSONHTTPCandidate:
    """One nonstreaming HTTP exchange per infer; retries are deliberately absent."""

    DEFAULTS = {"dialect": None, "timeout_seconds": 120.0, "max_tokens": 512,
                "temperature": 0.0, "top_p": 1.0, "api_key_env": None,
                "expected_system_fingerprint": None}
    DIALECTS = ()
    KIND = "json_http"
    NORMALIZATION = "none"
    REVISION_PROVENANCE = "configured"
    TASK_PROTOCOL_REF = None
    OUTPUT_SCHEMA_REF = None

    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)
        self.params = dict(self.DEFAULTS, **spec["params"])
        extra = set(self.params) - set(self.DEFAULTS) - {"base_url", "model", "model_revision"}
        if extra:
            _fail("invalid_config", "Unsupported HTTP candidate parameter", "configure")
        self.model = _text(self.params.get("model"), "model")
        self.revision = _text(self.params.get("model_revision"), "model_revision")
        base = _text(self.params.get("base_url"), "base_url")
        parsed = urllib.parse.urlsplit(base)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment):
            _fail("invalid_config", "base_url must be an HTTP URL without credentials/query/fragment", "configure")
        path = parsed.path.rstrip("/")
        path += "" if path.endswith("/chat/completions") else ("/chat/completions" if path.endswith("/v1") else "/v1/chat/completions")
        self.endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        if self.params["dialect"] not in self.DIALECTS:
            _fail("invalid_config", "An explicit supported HTTP dialect is required", "configure")
        _number(self.params["timeout_seconds"], "timeout_seconds", 1e-6)
        _number(self.params["max_tokens"], "max_tokens", 1, integer=True)
        _number(self.params["temperature"], "temperature", 0)
        _number(self.params["top_p"], "top_p", 1e-9, 1)
        if self.params["api_key_env"] is not None:
            name = _text(self.params["api_key_env"], "api_key_env")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                _fail("invalid_config", "api_key_env must name an environment variable", "configure")
        if self.params["expected_system_fingerprint"] is not None:
            _text(self.params["expected_system_fingerprint"], "expected_system_fingerprint")
        self._validate_controls()
        self.state, self.refs, self.key = "created", [], None
        self.observed_identity = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _validate_controls(self):
        """Validate service-specific generation controls in a concrete adapter."""

    def _representation_metadata(self):
        """Subclass hook for an explicit alternate input representation."""
        return {}

    def _redact(self, value):
        if isinstance(value, str):
            return value.replace(self.key, "[REDACTED]") if self.key else value
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            return {self._redact(key): self._redact(item) for key, item in value.items()}
        return value

    def _save(self, value):
        ref = self.resources.save_json(self._redact(value), "gymts.json/1")
        self.refs.append(ref)
        return ref

    def prepare(self, context, training):
        if self.state != "created":
            _fail("invalid_state", "Candidate prepare may be called only once", "prepare")
        if training is not None or context["learning"]["prepare"] != "load_only" or context["learning"]["online"] != "frozen":
            _fail("unsupported_capability", "The HTTP deployment supports frozen load_only inference", "prepare")
        if self.spec.get("artifact") is not None or self.spec.get("inherited_state"):
            _fail("unsupported_capability", "HTTP model state is managed by the fixed external deployment", "prepare")
        self.resources = context["resources"]
        if self.params["api_key_env"] is not None:
            self.key = os.environ.get(self.params["api_key_env"])
            if not self.key or any(ord(char) < 32 or ord(char) == 127 for char in self.key):
                self.key = None
                _fail("invalid_config", "Configured API credential is missing or invalid", "prepare")
        deployment = {"kind": self.KIND, "model": self.model,
                      "model_revision": self.revision, "revision_provenance": self.REVISION_PROVENANCE,
                      "revision_verified": False, "endpoint_fingerprint": hashlib.sha256(self.endpoint.encode()).hexdigest(),
                      "dialect": self.params["dialect"], "normalization": self.NORMALIZATION,
                      "generation": {key: self.params[key] for key in ("temperature", "top_p", "max_tokens")},
                      "expected_system_fingerprint": self.params["expected_system_fingerprint"],
                      "capture_profile": "core", "model_calls": "not_collected"}
        deployment.update(self._representation_metadata())
        ref = self._save(deployment)
        self.state = "prepared"
        return {"model_revision": self.revision, "state_refs": [ref], "training_provenance_ref": None}

    def _load_input(self, task_input):
        """Validate/decode the selected task contract without making an HTTP call."""
        raise NotImplementedError

    def _wire(self, model_input):
        """Encode the native request for the selected model service."""
        raise NotImplementedError

    def _request_metadata(self, model_input):
        """Return explicitly selected public input evidence, if any."""
        return {}

    def infer(self, task_input):
        if self.state != "prepared":
            _fail("invalid_state", "Candidate infer requires prepared state", "infer")
        model_input = self._load_input(task_input)
        wire = self._wire(model_input)
        request_ref = self._save({"input_id": task_input["input_id"], "captured_at": utc_now(),
                                  "wire_payload": wire, **self._request_metadata(model_input),
                                  "normalization": self.NORMALIZATION, "model_revision": self.revision,
                                  "revision_provenance": self.REVISION_PROVENANCE,
                                  **self._representation_metadata()})
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        request = urllib.request.Request(self.endpoint, data=canonical_json(wire), headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=self.params["timeout_seconds"]) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                error_bytes = error.read(16 * 1024 * 1024)
            except (OSError, TimeoutError):
                error_bytes = None
            finally:
                error.close()
            captured = {"http_status": status, "captured_at": utc_now()}
            if error_bytes is None:
                captured["body_unavailable"] = "response_read_failed"
            else:
                try:
                    captured["body"] = json.loads(error_bytes, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
                except (UnicodeError, ValueError):
                    captured["unparsed_body"] = error_bytes.decode("utf-8", errors="replace")
            response_ref = self._save(captured)
            _fail("candidate_failure", "HTTP model service rejected the request", "infer", http_status=status,
                  request_ref=request_ref, response_ref=response_ref)
        except (urllib.error.URLError, OSError, TimeoutError):
            _fail("candidate_failure", "HTTP model service transport failed; request was not retried", "infer", request_ref=request_ref)
        if len(raw) > 16 * 1024 * 1024:
            _fail("candidate_failure", "HTTP response exceeded the capture limit", "infer", request_ref=request_ref)
        try:
            body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        except (UnicodeError, ValueError):
            response_ref = self._save({"http_status": status, "unparsed_body": raw.decode("utf-8", errors="replace")})
            _fail("candidate_failure", "HTTP model service returned invalid JSON", "infer", request_ref=request_ref, response_ref=response_ref)
        response_ref = self._save({"http_status": status, "captured_at": utc_now(), "body": body})
        if not isinstance(body, dict):
            _fail("candidate_failure", "HTTP model service response must be an object", "infer", response_ref=response_ref)
        fingerprint = body.get("system_fingerprint")
        expected = self.params["expected_system_fingerprint"]
        if expected is not None and fingerprint != expected:
            _fail("candidate_failure", "HTTP deployment fingerprint differs from its fixed configuration", "infer", response_ref=response_ref)
        identity = {"model": body.get("model"), "system_fingerprint": fingerprint}
        if self.observed_identity is not None and identity != self.observed_identity:
            _fail("candidate_failure", "HTTP model service identity changed during frozen inference", "infer", response_ref=response_ref)
        self.observed_identity = identity
        try:
            choice = body["choices"][0]
            text = choice["message"]["content"]
            if isinstance(text, list):
                if any(not isinstance(part, dict) or part.get("type") != "text" or not isinstance(part.get("text"), str) for part in text):
                    raise ValueError("unsupported content")
                text = "".join(part["text"] for part in text)
            if not isinstance(text, str):
                raise ValueError("missing text")
        except (KeyError, IndexError, TypeError, ValueError):
            _fail("candidate_failure", "HTTP model service response lacks generated textual content", "infer", response_ref=response_ref)
        evidence = {"kind": self.KIND, "request_ref": request_ref, "response_ref": response_ref,
                    "configured_model_revision": self.revision, "revision_provenance": self.REVISION_PROVENANCE,
                    "response_model": identity["model"], "system_fingerprint": fingerprint,
                    "usage": self._redact(body.get("usage")), "finish_reason": choice.get("finish_reason"),
                    "capture_profile": "core", "model_calls": "not_collected",
                    "missing": ["native_token_ids", "native_logprobs", "processor_revision"]}
        evidence.update(self._representation_metadata())
        evidence["normalization"] = self.NORMALIZATION
        return {"input_id": task_input["input_id"], "task_protocol_ref": self.TASK_PROTOCOL_REF,
                "produced_at": utc_now(), "model_revision": self.revision,
                "payload": payload(self.OUTPUT_SCHEMA_REF, {"raw_text": self._redact(text), "evidence": self._redact(evidence)})}

    def update(self, feedback):
        _fail("unsupported_capability", "The HTTP adapter has no online update interface", "update")

    def finish(self):
        self.key = None
        self.state = "closed"
        return copy.deepcopy(self.refs)


__all__ = ["FrozenJSONHTTPCandidate"]
