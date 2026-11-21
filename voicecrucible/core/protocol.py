"""Wire format shared by coordinator and worker: discovery messages, pairing proof, fingerprints.

Discovery: a worker broadcasts a small query on the LAN, the coordinator answers with its ID, API port and
certificate fingerprint. Answers are not trusted on their own – after pairing the worker only talks to the
certificate it pinned. Pairing: the worker proves it knows the one-time code by sending
HMAC(code, fingerprint|worker_id), which also binds the code to the certificate the worker really sees.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

APP = "voicecrucible"
PROTOCOL_VERSION = 1
# Oldest worker protocol the coordinator still serves. Keep new coordinators compatible with the previous
# protocol, so workers can be updated first and the coordinator last without breaking the render.
MIN_COMPATIBLE = 1
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I – easy to read and type
CODE_LENGTH = 10


def fingerprint(der_cert: bytes) -> str:
    """SHA-256 fingerprint of a DER certificate as lowercase hex."""
    return hashlib.sha256(der_cert).hexdigest()


def short_fingerprint(fp: str) -> str:
    """Readable short form of a fingerprint for logs and the watcher (e.g. 'a1b2-c3d4-e5f6')."""
    return "-".join(fp[i:i + 4] for i in range(0, 12, 4))


def normalize_code(code: str) -> str:
    """Pairing code without dashes/spaces, upper case – so 'abcde-fghjk' and 'ABCDEFGHJK' match."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


def format_code(code: str) -> str:
    """Pairing code split into two halves for display: 'ABCDE-FGHJK'."""
    half = len(code) // 2
    return f"{code[:half]}-{code[half:]}"


def pairing_proof(code: str, cert_fingerprint: str, worker_id: str) -> str:
    """Proof that a worker knows the pairing code, bound to the certificate it sees."""
    msg = f"{cert_fingerprint}|{worker_id}".encode()
    return hmac.new(normalize_code(code).encode(), msg, hashlib.sha256).hexdigest()


def make_query() -> bytes:
    """Discovery query a worker broadcasts on the LAN."""
    return json.dumps({"app": APP, "v": PROTOCOL_VERSION, "q": "discover"}).encode()


def is_query(data: bytes) -> bool:
    """True when `data` is a valid discovery query."""
    msg = _parse(data)
    return msg is not None and msg.get("q") == "discover"


def make_beacon(coordinator_id: str, port: int, cert_fingerprint: str) -> bytes:
    """Coordinator's answer to a discovery query."""
    return json.dumps({"app": APP, "v": PROTOCOL_VERSION, "id": coordinator_id,
                       "port": port, "fp": cert_fingerprint}).encode()


def parse_beacon(data: bytes) -> dict[str, Any] | None:
    """Decode a coordinator answer; None when it is not a valid Voice Crucible beacon."""
    msg = _parse(data)
    if msg is None:
        return None
    if not (isinstance(msg.get("id"), str) and isinstance(msg.get("fp"), str)
            and isinstance(msg.get("port"), int) and 1 <= msg["port"] <= 65535):
        return None
    return {"id": msg["id"], "port": msg["port"], "fp": msg["fp"]}


def _parse(data: bytes) -> dict[str, Any] | None:
    """Decode a small JSON datagram of our app and protocol version, else None."""
    if len(data) > 1024:
        return None
    try:
        msg = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict) or msg.get("app") != APP or msg.get("v") != PROTOCOL_VERSION:
        return None
    return msg
