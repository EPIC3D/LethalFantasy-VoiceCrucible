"""Pairing: one-time codes shown on the coordinator, and the per-worker tokens they are exchanged for.

Only SHA-256 hashes of tokens are stored (workers.json), so the file cannot be used to impersonate a worker.
A code is valid for a few minutes, works once, and is burnt after a few wrong attempts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

from voicecrucible.core import protocol

MAX_WRONG_ATTEMPTS = 5


def _hash(token: str) -> str:
    """SHA-256 of a token, as stored on disk."""
    return hashlib.sha256(token.encode()).hexdigest()


class Pairing:
    """Issues pairing codes and checks worker tokens."""

    def __init__(self, workers_file: Path, cert_fingerprint: str, code_minutes: float = 10):
        self._file = workers_file
        self._fingerprint = cert_fingerprint
        self._code_seconds = code_minutes * 60
        self._lock = threading.Lock()
        self._code = ""
        self._code_until = 0.0
        self._wrong = 0
        self._workers: dict[str, dict] = json.loads(workers_file.read_text("utf-8")) if workers_file.exists() else {}

    def new_code(self) -> str:
        """Create a fresh one-time code (replaces the previous one) and return it formatted for display."""
        with self._lock:
            self._code = "".join(secrets.choice(protocol.CODE_ALPHABET) for _ in range(protocol.CODE_LENGTH))
            self._code_until = time.time() + self._code_seconds
            self._wrong = 0
            return protocol.format_code(self._code)

    def current_code(self) -> tuple[str, float] | None:
        """The active code and its expiry time, or None when there is no valid code."""
        with self._lock:
            if not self._code or time.time() >= self._code_until:
                return None
            return protocol.format_code(self._code), self._code_until

    def pair(self, worker_id: str, name: str, proof: str) -> str | None:
        """Exchange a valid proof for a new token (returned once, never stored in plain text); None if invalid."""
        with self._lock:
            if not self._code or time.time() >= self._code_until:
                return None
            expected = protocol.pairing_proof(self._code, self._fingerprint, worker_id)
            if not hmac.compare_digest(expected, proof):
                self._wrong += 1
                if self._wrong >= MAX_WRONG_ATTEMPTS:
                    self._code = ""
                return None
            self._code = ""  # one-time
            token = secrets.token_urlsafe(32)
            self._workers[worker_id] = {"name": name[:64], "token_sha256": _hash(token), "paired_at": int(time.time())}
            self._save_locked()
            return token

    def check(self, token: str) -> str | None:
        """Worker ID belonging to a token, or None for unknown/revoked tokens."""
        h = _hash(token)
        with self._lock:
            for worker_id, info in self._workers.items():
                if hmac.compare_digest(info["token_sha256"], h):
                    return worker_id
        return None

    def revoke(self, worker_id: str) -> bool:
        """Remove a worker; its token stops working immediately."""
        with self._lock:
            if self._workers.pop(worker_id, None) is None:
                return False
            self._save_locked()
            return True

    def paired(self) -> dict[str, dict]:
        """Paired workers: ID -> name and pairing time (no token data)."""
        with self._lock:
            return {wid: {"name": i["name"], "paired_at": i["paired_at"]} for wid, i in self._workers.items()}

    def _save_locked(self) -> None:
        """Write workers.json atomically (caller holds the lock)."""
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._workers, indent=2), encoding="utf-8")
        tmp.replace(self._file)
