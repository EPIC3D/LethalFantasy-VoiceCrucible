"""Local-only HTTP server for the watcher page (bound to 127.0.0.1, never reachable from the network).

Actions (new pairing code, revoke a worker) require a custom header, which a foreign web page cannot send
to localhost without a CORS preflight that this server never approves.
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from voicecrucible import __version__
from voicecrucible.coordinator.app import CoordinatorState
from voicecrucible.core import log, protocol

_log = log.get(__name__)
_PAGE = Path(__file__).with_name("index.html")
ACTION_HEADER = "X-Voice-Crucible"


def _compare(version: str) -> str:
    """'older' / 'newer' / 'same' compared with this coordinator ('' when unknown)."""
    from voicecrucible.installer.update import UpdateError, _version_tuple
    if not version:
        return ""
    try:
        mine, theirs = _version_tuple(__version__), _version_tuple(version)
    except UpdateError:
        return ""
    return "same" if theirs == mine else "older" if theirs < mine else "newer"


def status(state: CoordinatorState) -> dict:
    """Everything the watcher page shows, as one JSON object."""
    counts = state.queue.counts()
    workers = state.registry.snapshot()
    paired = state.pairing.paired()
    for wid, info in paired.items():
        if not any(w["worker_id"] == wid for w in workers):
            workers.append({"worker_id": wid, "name": info["name"], "online": False, "gpus": [], "done": 0,
                            "failed": 0, "busy_lines": 0, "lines_per_min": 0, "address": "", "version": "",
                            "accepts_updates": False, "update_status": ""})
    for w in workers:
        w["version_state"] = _compare(w.get("version", ""))
    speed = sum(w["lines_per_min"] for w in workers if w["online"])
    remaining = counts["pending"] + counts["leased"]
    code = state.pairing.current_code()
    return {
        "coordinator_id": state.identity.coordinator_id,
        "version": __version__,
        "fingerprint": protocol.short_fingerprint(state.identity.fingerprint),
        "counts": counts,
        "eta_seconds": round(remaining / speed * 60) if speed > 0 and remaining else None,
        "workers": workers,
        "problems": state.queue.recent_problems(),
        "pairing_code": None if code is None else {"code": code[0], "seconds_left": round(code[1] - time.time())},
    }


def make_server(state: CoordinatorState, port: int) -> ThreadingHTTPServer:
    """Create the watcher server on 127.0.0.1 (not started)."""

    class Handler(BaseHTTPRequestHandler):
        """Serves the page, its status JSON and two actions."""

        server_version = "VoiceCrucible"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(200, _PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json(200, status(state))
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get(ACTION_HEADER) != "1":
                self._json(403, {"error": "missing action header"})
                return
            if self.path == "/api/pairing-code":
                code = state.pairing.new_code()
                _log.info("new pairing code created in the watcher")
                self._json(200, {"code": code})
            elif self.path == "/api/request-update":
                names = state.registry.request_update()
                _log.info("update requested in the watcher for: %s", ", ".join(names) or "nobody")
                self._json(200, {"workers": names})
            elif self.path == "/api/revoke":
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 4096)
                    worker_id = json.loads(self.rfile.read(length) or b"{}").get("worker_id", "")
                except (ValueError, AttributeError):
                    worker_id = ""
                ok = isinstance(worker_id, str) and state.pairing.revoke(worker_id)
                if ok:
                    state.registry.forget(worker_id)
                    _log.info("worker %s revoked in the watcher", worker_id)
                self._json(200 if ok else 404, {"revoked": ok})
            else:
                self._json(404, {"error": "not found"})

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _send(self, code: int, data: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args) -> None:
            pass  # the page polls every few seconds; keep the log clean

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
