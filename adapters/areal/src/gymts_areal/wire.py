"""Small private Unix-socket wire protocol, with bounded finite JSON messages."""
from datetime import datetime, timezone
import hashlib
import json
import math
import socket

MAX_MESSAGE = 64 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def finite_evidence(value):
    """Represent invalid native scalars explicitly in failure evidence only."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"native_nonfinite_float": str(value)}
    if isinstance(value, dict):
        return {key: finite_evidence(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_evidence(item) for item in value]
    return value


def send(stream, value):
    data = canonical(value)
    if len(data) > MAX_MESSAGE:
        raise ValueError("AReaL bridge message exceeds the declared finite size limit")
    stream.write(data + b"\n")
    stream.flush()


def receive(stream):
    raw = stream.readline(MAX_MESSAGE + 2)
    if not raw or len(raw) > MAX_MESSAGE + 1 or not raw.endswith(b"\n"):
        raise RuntimeError("AReaL bridge disconnected or returned an oversized/incomplete message")
    return json.loads(raw)


class Client:
    def __init__(self, path, *, timeout=600):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.socket.connect(path)
        self.stream = self.socket.makefile("rwb")
        self.sequence = 0

    def request(self, message):
        send(self.stream, message)
        answer = receive(self.stream)
        if answer.get("kind") == "error":
            raise RuntimeError("AReaL host rejected operation: " + answer["message"])
        return answer

    def event(self, kind, **fields):
        self.sequence += 1
        reply = self.request({"kind": kind, "sequence": self.sequence, "at": now(), **fields})
        if reply != {"kind": "ack", "sequence": self.sequence}:
            raise RuntimeError("Host did not acknowledge committed native evidence")

    def close(self):
        self.stream.close()
        self.socket.close()
