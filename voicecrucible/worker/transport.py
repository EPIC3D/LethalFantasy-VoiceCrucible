"""HTTPS requests to the coordinator with certificate pinning.

There is no certificate authority: the worker checks that the coordinator's certificate has exactly the
fingerprint it saved when pairing, before any data (token, audio) is sent.
"""

from __future__ import annotations

import hmac
import http.client
import json
import ssl
from collections.abc import Callable
from typing import Any

from voicecrucible.core import protocol


class FingerprintMismatch(ConnectionError):
    """The coordinator presented a different certificate than the one pinned at pairing."""


class Connection:
    """Sends JSON POST requests to one coordinator address."""

    def __init__(self, host: str, port: int, fingerprint: str = "", token: str = "", timeout: float = 60):
        self.host, self.port, self.fingerprint, self.token, self.timeout = host, port, fingerprint, token, timeout
        self.seen_fingerprint = ""

    def post(self, path: str, payload: dict | Callable[[str], dict]) -> tuple[int, dict[str, Any]]:
        """POST JSON and return (status, answer). `payload` may be a function of the certificate fingerprint seen."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # trust comes from the pinned fingerprint below
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        try:
            conn.connect()
            self.seen_fingerprint = protocol.fingerprint(conn.sock.getpeercert(binary_form=True))
            if self.fingerprint and not hmac.compare_digest(self.seen_fingerprint, self.fingerprint):
                raise FingerprintMismatch(
                    f"coordinator at {self.host}:{self.port} has an unknown certificate "
                    f"({protocol.short_fingerprint(self.seen_fingerprint)}, expected "
                    f"{protocol.short_fingerprint(self.fingerprint)})")
            body = payload(self.seen_fingerprint) if callable(payload) else payload
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            conn.request("POST", path, json.dumps(body).encode(), headers)
            try:
                resp = conn.getresponse()
                raw = resp.read()
            except http.client.HTTPException as e:  # e.g. connection cut mid-answer
                raise ConnectionError(f"incomplete answer from the coordinator: {e!r}") from e
            try:
                answer = json.loads(raw) if raw else {}
            except ValueError:
                answer = {"error": raw[:200].decode("utf-8", "replace")}
            return resp.status, answer if isinstance(answer, dict) else {}
        finally:
            conn.close()
