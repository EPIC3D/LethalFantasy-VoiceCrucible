"""Worker main loop and pairing: find the coordinator, heartbeat, claim a job, render, upload, repeat.

The worker only ever connects out to its paired coordinator (pinned certificate). If the coordinator's
address changes (DHCP), it is found again by its ID on the LAN. A certificate mismatch stops the worker.
"""

from __future__ import annotations

import base64
import os
import threading
from pathlib import Path

from voicecrucible import __version__
from voicecrucible.core import log, protocol
from voicecrucible.core.config import Config
from voicecrucible.core.jobs import Job
from voicecrucible.engines import seedvc
from voicecrucible.worker import discovery, gpu, identity
from voicecrucible.worker.assets import AssetCache
from voicecrucible.worker.runner import Runner
from voicecrucible.worker.transport import Connection, FingerprintMismatch

_log = log.get(__name__)
HEARTBEAT_SECONDS = 10
IDLE_POLL_SECONDS = 5
MAX_BACKOFF_SECONDS = 60
RESTART_EXIT_CODE = 75  # "updated – start me again": worker.cmd restarts the worker on this code


class PairingError(RuntimeError):
    """Pairing failed; the message says why and what to do."""


class NotPaired(RuntimeError):
    """The worker has no valid pairing (never paired, or revoked on the coordinator)."""


def identity_path(cfg: Config) -> Path:
    """Where this machine's worker identity is stored."""
    return cfg.path(cfg.paths.work_dir) / "worker" / "identity.json"


def _split_host(value: str, default_port: int) -> tuple[str, int]:
    """'host' or 'host:port' -> (host, port)."""
    host, sep, port = value.rpartition(":")
    if sep and port.isdigit():
        return host, int(port)
    return value, default_port


def pair(cfg: Config, code: str, coordinator: str = "") -> identity.WorkerIdentity:
    """Pair this machine with a coordinator using its one-time code; saves the token and pinned certificate."""
    ident = identity.load(identity_path(cfg), cfg.worker.name)
    target = coordinator or cfg.worker.coordinator
    if target:
        host, port = _split_host(target, cfg.coordinator.port)
    else:
        found = discovery.find_coordinators(cfg.coordinator.discovery_port)
        if not found:
            raise PairingError("no coordinator found on the local network – is 'crucible coordinator' running? "
                               "You can also give its address: crucible pair <code> --coordinator <host>")
        if len(found) > 1:
            names = ", ".join(f"{c['host']} ({c['id']})" for c in found)
            raise PairingError(f"several coordinators found: {names} – choose one with --coordinator <host>")
        host, port = found[0]["host"], found[0]["port"]
    conn = Connection(host, port, timeout=15)
    status, answer = conn.post("/api/pair", lambda fp: {
        "worker_id": ident.worker_id, "name": ident.name,
        "proof": protocol.pairing_proof(code, fp, ident.worker_id)})
    if status != 200:
        raise PairingError(answer.get("error", f"coordinator answered {status}"))
    ident.token, ident.coordinator_id = answer["token"], answer["coordinator_id"]
    ident.fingerprint, ident.host, ident.port = conn.seen_fingerprint, host, port
    identity.save(identity_path(cfg), ident)
    return ident


class WorkerClient:
    """Runs jobs for the paired coordinator until `stop` is set."""

    def __init__(self, cfg: Config, runner: Runner):
        self.cfg = cfg
        self.runner = runner
        self.ident = identity.load(identity_path(cfg), cfg.worker.name)
        if not self.ident.paired:
            raise NotPaired("this worker is not paired yet – run: crucible pair <code>")
        self.stop = threading.Event()
        self._busy_lines = 0
        self._conn: Connection | None = None
        self._conn_lock = threading.Lock()
        self._unsent: dict | None = None  # results whose upload failed; sent before claiming new work
        self._job: Job | None = None  # job held right now (rendered or not), handed back on stop
        self._update_wanted = threading.Event()  # set by a coordinator's update request (if allowed)
        self._update_status = ""
        self.exit_code = 0
        if runner.voice_path is None:
            cache = AssetCache(cfg.path(cfg.paths.work_dir) / "worker" / "assets", self._fetch_asset)
            runner.voice_path = cache.get

    def _fetch_asset(self, sha: str) -> dict:
        """Download one reference voice from the coordinator."""
        status, answer = self._post("/api/asset", {"sha256": sha})
        self._check(status, answer)
        return answer

    def run(self) -> None:
        """Main loop: claim, render, upload; reconnects with back-off when the coordinator is unreachable."""
        beat = threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)
        beat.start()
        backoff = IDLE_POLL_SECONDS
        try:
            while not self.stop.is_set():
                try:
                    if self._unsent is not None:
                        self._upload(self._unsent)
                    if self._update_wanted.is_set() and self._self_update():
                        break  # between jobs: nothing is held; worker.cmd restarts the new version
                    status, answer = self._post("/api/claim", {"max_lines": self.runner.batch_size})
                    self._check(status, answer)
                    backoff = IDLE_POLL_SECONDS
                    if answer.get("job") is None:
                        self.stop.wait(IDLE_POLL_SECONDS)
                        continue
                    self._process(Job.from_dict(answer["job"]))
                except OSError as e:  # includes connection errors; FingerprintMismatch is re-raised below
                    if isinstance(e, FingerprintMismatch):
                        raise
                    _log.warning("coordinator not reachable (%s) – retrying in %d s", e, backoff)
                    with self._conn_lock:
                        self._conn = None
                    self.stop.wait(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
        finally:
            self.stop.set()
            self._hand_back()
            self.runner.close()

    def _self_update(self) -> bool:
        """Update this worker from GitHub after a coordinator's request. The coordinator sends no code: the
        worker downloads the release itself and checks the signature with its own built-in key.
        True = installed (the worker stops with RESTART_EXIT_CODE so worker.cmd starts the new version)."""
        from voicecrucible.installer import update
        self._update_wanted.clear()
        self._update_status = "updating"
        _log.info("the coordinator asked for an update – checking GitHub")
        try:
            rel = update.latest()
            if not update.is_newer(rel["version"]):
                self._update_status = f"up to date ({__version__})"
                _log.info("already the latest version (%s)", __version__)
                return False
            version = update.download_and_install(rel)
        except (update.UpdateError, OSError, ValueError, KeyError) as e:
            self._update_status = f"failed: {e}"
            _log.error("self-update failed, this version keeps running: %s", e)
            return False
        _log.info("updated to %s – restarting", version)
        self.exit_code = RESTART_EXIT_CODE
        return True

    def _hand_back(self) -> None:
        """On stop: deliver finished results, or give an unfinished job back, so nothing waits for a lease timeout."""
        try:
            if self._unsent is not None:
                self._upload(self._unsent)
            elif self._job is not None:
                self._release(self._job, "worker stopped", failed=False)
        except (OSError, NotPaired) as e:
            _log.debug("could not hand back work on stop (the lease will expire instead): %s", e)
        except KeyboardInterrupt:
            pass  # second Ctrl+C: stop immediately

    def _process(self, job: Job) -> None:
        """Render one job and upload the results; on error give the job back."""
        _log.info("job %s: %d line(s), engine '%s'", job.job_id[:8], len(job.lines), job.engine)
        self._job = job
        self._busy_lines = len(job.lines)
        try:
            takes = self.runner.render(job)
        except Exception as e:
            _log.exception("job %s failed", job.job_id[:8])
            self._release(job, f"worker error: {e}", failed=True)
            return
        finally:
            self._busy_lines = 0
        self._unsent = {"job_id": job.job_id, "takes": [
            {"uid": t.uid, "passed": t.passed, "reason": t.reason, "ext": t.ext, "score": t.score,
             "audio": base64.b64encode(t.audio).decode("ascii")} for t in takes]}
        self._upload(self._unsent)

    def _upload(self, payload: dict) -> None:
        """Send results; kept in `_unsent` until the coordinator confirmed them."""
        status, answer = self._post("/api/result", payload)
        self._check(status, answer)
        self._unsent = None
        self._job = None
        _log.info("job %s: %d result(s) delivered", payload["job_id"][:8], answer.get("accepted", 0))

    def _release(self, job: Job, reason: str, failed: bool) -> None:
        """Give a job back to the coordinator (best effort)."""
        self._job = None
        try:
            self._post("/api/release", {"job_id": job.job_id, "reason": reason, "failed": failed})
        except OSError as e:
            _log.debug("release failed (the lease will expire instead): %s", e)

    def _heartbeat_loop(self) -> None:
        """Report GPU state every few seconds so the coordinator keeps our leases alive."""
        while not self.stop.is_set():
            try:
                job = self._job
                status, answer = self._post("/api/heartbeat", {
                    "gpus": gpu.query(), "busy_lines": self._busy_lines, "job_id": job.job_id if job else "",
                    "version": __version__, "protocol": protocol.PROTOCOL_VERSION,
                    "accepts_updates": self.cfg.worker.allow_update_requests, "update_status": self._update_status})
                if status in (401, 426):
                    _log.error(answer.get("error", "the coordinator refused this worker"))
                    self.stop.set()
                elif answer.get("update_requested") and self.cfg.worker.allow_update_requests:
                    self._update_wanted.set()  # done between two jobs by the main loop
            except FingerprintMismatch as e:
                _log.error("SECURITY: %s – stopping. If you reinstalled the coordinator, pair again.", e)
                self.stop.set()
            except OSError:
                pass  # the main loop reports connection problems
            self.stop.wait(HEARTBEAT_SECONDS)

    def _check(self, status: int, answer: dict) -> None:
        """Turn error answers into exceptions the loop understands."""
        if status == 401:
            raise NotPaired(answer.get("error", "pairing revoked"))
        if status == 426:
            raise NotPaired(answer.get("error", "this worker is too old for the coordinator – update it"))
        if status != 200:
            raise ConnectionError(answer.get("error", f"coordinator answered {status}"))

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        """POST to the coordinator, locating it first if needed."""
        with self._conn_lock:
            conn = self._conn or self._locate()
        return conn.post(path, payload)

    def _locate(self) -> Connection:
        """Find the paired coordinator: configured address, last known address, or LAN discovery by ID."""
        ident = self.ident
        if self.cfg.worker.coordinator:
            host, port = _split_host(self.cfg.worker.coordinator, ident.port or self.cfg.coordinator.port)
        else:
            match = [c for c in discovery.find_coordinators(self.cfg.coordinator.discovery_port, timeout=2.0)
                     if c["id"] == ident.coordinator_id]
            if match:
                host, port = match[0]["host"], match[0]["port"]
            else:
                host, port = ident.host, ident.port  # discovery may be blocked; try the last address
            if (host, port) != (ident.host, ident.port):
                _log.info("coordinator found at %s:%d", host, port)
                ident.host, ident.port = host, port
                identity.save(identity_path(self.cfg), ident)
        self._conn = Connection(host, port, ident.fingerprint, ident.token)
        return self._conn


def run(cfg: Config) -> int:
    """`crucible worker`: work until Ctrl+C."""
    os.environ.setdefault(seedvc.ENV_DIR, str(cfg.path(cfg.worker.seedvc_dir)))
    try:
        client = WorkerClient(cfg, Runner(gpu.default_device(), cfg.worker.max_batch))
    except NotPaired as e:
        _log.error("%s", e)
        return 1
    _log.info("worker '%s' started – press Ctrl+C to stop", client.ident.name)
    try:
        client.run()
    except KeyboardInterrupt:
        _log.info("stopped")
    except NotPaired as e:
        _log.error("%s", e)
        return 1
    except FingerprintMismatch as e:
        _log.error("SECURITY: %s – stopping. If you reinstalled the coordinator, pair again.", e)
        return 1
    return client.exit_code
