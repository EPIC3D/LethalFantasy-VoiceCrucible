"""The coordinator's HTTPS API for workers: pair, heartbeat, claim a job, upload results, release a job.

Rules enforced here: requests only from local/private addresses, a size limit on every body, a valid
worker token on everything except /api/pair, and leases checked so a worker can only report its own lines.
"""

from __future__ import annotations

import base64
import binascii
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from voicecrucible.coordinator import results
from voicecrucible.coordinator.assets import AssetStore
from voicecrucible.coordinator.discovery import is_local_address
from voicecrucible.coordinator.pairing import Pairing
from voicecrucible.coordinator.scheduler import WorkerRegistry
from voicecrucible.coordinator.tls import CoordinatorIdentity
from voicecrucible.core import log, protocol
from voicecrucible.core.queue import JobQueue

_log = log.get(__name__)
MAX_BODY_BYTES = 256 * 1024 * 1024


@dataclass
class CoordinatorState:
    """Everything the API handlers need, shared between request threads."""

    identity: CoordinatorIdentity
    queue: JobQueue
    pairing: Pairing
    registry: WorkerRegistry
    output_root: Path
    language: str
    assets: AssetStore
    check_settings: dict
    takes_dir: Path  # failed takes kept as fallback candidates
    log_dir: Path | None = None  # shown in the watcher
    profile: str = ""  # active profile name, shown in the watcher
    leftover: dict | None = None  # an unfinished render found at start: {"lines", "since"}; rendering starts paused
    stop_event: threading.Event = field(default_factory=threading.Event)  # set to end the coordinator (watcher: run setup)


class ApiError(Exception):
    """An error answered with an HTTP status and a short message."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def make_server(state: CoordinatorState, host: str, port: int) -> ThreadingHTTPServer:
    """Create the TLS API server (not started)."""
    server = ThreadingHTTPServer((host, port), _make_handler(state))
    server.daemon_threads = True
    server.socket = state.identity.server_context().wrap_socket(server.socket, server_side=True)
    return server


def _make_handler(state: CoordinatorState) -> type[BaseHTTPRequestHandler]:
    """Build the request handler class bound to `state`."""

    class Handler(BaseHTTPRequestHandler):
        """Routes POST /api/* to the handler functions below."""

        server_version = "VoiceCrucible"
        sys_version = ""
        # HTTP/1.1: the client closes the connection after reading the answer. With HTTP/1.0 the server
        # closed first, and Windows sometimes reset the connection before the answer was read.
        protocol_version = "HTTP/1.1"
        timeout = 60  # drop idle keep-alive connections

        def do_POST(self) -> None:  # noqa: N802 (http.server naming)
            route = _ROUTES.get(self.path)
            try:
                if not is_local_address(self.client_address[0]):
                    raise ApiError(403, "only local network clients are allowed")
                if route is None:
                    raise ApiError(404, "unknown endpoint")
                body = self._read_json()
                worker_id = None if self.path == "/api/pair" else self._auth()
                status, answer = route(state, worker_id, body, self.client_address[0])
            except ApiError as e:
                status, answer = e.status, {"error": str(e)}
            except Exception:  # never let one bad request kill the server
                _log.exception("error in %s", self.path)
                status, answer = 500, {"error": "internal error, see the coordinator log"}
            self._send(status, answer)

        def do_GET(self) -> None:  # noqa: N802
            self._send(404, {"error": "this is the worker API, not a web page – the watcher is "
                                      "http://127.0.0.1:5132 on the coordinator computer (watcher.cmd)"})

        def _read_json(self) -> dict:
            """Read and decode the JSON body, enforcing the size limit."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ApiError(400, "bad Content-Length") from None
            if not 0 <= length <= MAX_BODY_BYTES:
                raise ApiError(413, "request too large")
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                raise ApiError(400, "body is not JSON") from None
            if not isinstance(data, dict):
                raise ApiError(400, "body must be a JSON object")
            return data

        def _auth(self) -> str:
            """Worker ID from the bearer token, or 401."""
            header = self.headers.get("Authorization", "")
            worker_id = state.pairing.check(header[7:]) if header.startswith("Bearer ") else None
            if worker_id is None:
                raise ApiError(401, "not paired or pairing revoked – run 'crucible pair' on the worker")
            return worker_id

        def _send(self, status: int, answer: dict) -> None:
            """Send a JSON answer."""
            data = json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args) -> None:
            _log.debug("%s %s", self.client_address[0], fmt % args)

    return Handler


def _str(body: dict, key: str, max_len: int = 200) -> str:
    """Required short string field."""
    value = body.get(key)
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise ApiError(400, f"'{key}' missing or invalid")
    return value


def _pair(state: CoordinatorState, _worker: str | None, body: dict, address: str) -> tuple[int, dict]:
    """Exchange a pairing proof for a token."""
    worker_id, name = _str(body, "worker_id", 64), _str(body, "name", 64)
    token = state.pairing.pair(worker_id, name, _str(body, "proof", 128))
    if token is None:
        _log.warning("pairing attempt from %s (%s) rejected", address, name)
        raise ApiError(403, "pairing code wrong or expired – get a new code in the watcher")
    _log.info("worker '%s' paired from %s", name, address)
    return 200, {"token": token, "coordinator_id": state.identity.coordinator_id}


def _heartbeat(state: CoordinatorState, worker: str, body: dict, address: str) -> tuple[int, dict]:
    """Keep the worker's leases alive and update the watcher."""
    protocol_version = body.get("protocol") if isinstance(body.get("protocol"), int) else 1
    if protocol_version < protocol.MIN_COMPATIBLE:
        raise ApiError(426, "this worker is too old for the coordinator – update it (crucible update)")
    gpus = body.get("gpus") if isinstance(body.get("gpus"), list) else []
    busy = body.get("busy_lines") if isinstance(body.get("busy_lines"), int) else 0
    name = state.pairing.paired().get(worker, {}).get("name", worker)
    update_now = state.registry.seen(worker, name, address, [g for g in gpus if isinstance(g, dict)], busy,
                                     str(body.get("version", "")), body.get("accepts_updates") is True,
                                     str(body.get("update_status", "")), body.get("progress"),
                                     str(body.get("session", "")),
                                     body.get("features") if isinstance(body.get("features"), list) else [])
    job_id = body.get("job_id")
    commands = state.registry.commands(worker)
    if isinstance(job_id, str) and job_id:
        state.queue.touch(worker, job_id[:64])
        if job_id[:64] in state.queue.cancelled_jobs:  # its lines were removed (Cancel render): stop working on it
            commands["cancel"] = True
    return 200, {"ok": True, "update_requested": update_now, "protocol": protocol.PROTOCOL_VERSION, **commands}


def _claim(state: CoordinatorState, worker: str, body: dict, _address: str) -> tuple[int, dict]:
    """Hand out the next job, or {"job": null} when the queue is empty, rendering is paused or the worker stopped."""
    requested = body.get("max_lines") if isinstance(body.get("max_lines"), int) else 1
    if not state.registry.may_claim(worker):
        return 200, {"job": None}
    job = state.queue.claim(worker, state.registry.batch_size(requested))
    if job is not None:
        job.settings = {} if job.engine == "test" else state.check_settings  # beeps would fail every check
    return 200, {"job": None if job is None else job.to_dict()}


def _asset(state: CoordinatorState, _worker: str, body: dict, _address: str) -> tuple[int, dict]:
    """Send one reference voice by its SHA-256 (only files in the asset store exist for this)."""
    path = state.assets.get(_str(body, "sha256", 64))
    if path is None:
        raise ApiError(404, "unknown asset")
    return 200, {"ext": path.suffix, "data": base64.b64encode(path.read_bytes()).decode("ascii")}


def _result(state: CoordinatorState, worker: str, body: dict, _address: str) -> tuple[int, dict]:
    """Store passed takes, requeue failed ones. Lines not held by this lease are ignored."""
    job_id = _str(body, "job_id", 64)
    takes = body.get("takes")
    if not isinstance(takes, list):
        raise ApiError(400, "'takes' missing")
    accepted = done = failed = 0
    for take in takes:
        if not isinstance(take, dict) or not isinstance(take.get("uid"), int):
            continue
        line = state.queue.leased_line(job_id, take["uid"], worker)
        if line is None:
            continue
        passed, reason = take.get("passed") is True, str(take.get("reason", ""))[:500]
        ext = str(take.get("ext", ""))
        output = candidate = ""
        try:
            audio = base64.b64decode(str(take.get("audio", "")), validate=True)
            if passed:
                path = results.save(state.output_root, state.language, line, ext, audio)
                output = path.relative_to(state.output_root).as_posix()
            elif audio:  # keep a failed take as a fallback, in case every attempt fails
                candidate = str(results.save_candidate(state.takes_dir, line, ext, audio))
        except (binascii.Error, ValueError) as e:
            passed, reason = False, f"bad audio from worker: {e}"
        score = take.get("score") if isinstance(take.get("score"), (int, float)) else -1.0
        status = state.queue.finish(job_id, line.uid, passed, reason, output, candidate, float(score))
        if status == "failed":
            _export_best_take(state, line)
        accepted += 1
        done, failed = done + passed, failed + (not passed)
    state.registry.record(worker, done, failed)
    return 200, {"accepted": accepted}


def _bye(state: CoordinatorState, worker: str, body: dict, _address: str) -> tuple[int, dict]:
    """The worker program is closing; its reason is shown in the watcher."""
    state.registry.goodbye(worker, str(body.get("reason", ""))[:200])
    return 200, {"ok": True}


def _export_best_take(state: CoordinatorState, line) -> None:
    """A line failed every attempt: export its best take anyway (like the original pipeline) and note it."""
    best = state.queue.best_take(line.uid)
    if not best or not Path(best).exists():
        return
    path = results.save(state.output_root, state.language, line, Path(best).suffix.lstrip("."), Path(best).read_bytes())
    state.queue.set_output(line.uid, path.relative_to(state.output_root).as_posix())
    _log.info("%s failed every check – best take exported, listed in the report", line.file_stem)


def _release(state: CoordinatorState, worker: str, body: dict, _address: str) -> tuple[int, dict]:
    """Give a job back (worker stopping = no attempt counted; worker error = counted)."""
    failed = body.get("failed") is True
    reason = str(body.get("reason", "worker error"))[:500] if failed else ""  # a normal stop is not a problem
    n = state.queue.release(_str(body, "job_id", 64), worker, reason, count_attempt=failed)
    return 200, {"released": n}


_ROUTES = {"/api/pair": _pair, "/api/heartbeat": _heartbeat, "/api/claim": _claim,
           "/api/result": _result, "/api/release": _release, "/api/asset": _asset, "/api/bye": _bye}
