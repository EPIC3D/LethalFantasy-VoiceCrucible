"""Live state of the workers (heartbeats, GPU load, speed) and how many lines each one gets per job."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field

OFFLINE_AFTER_SECONDS = 30


@dataclass
class WorkerState:
    """What the coordinator knows about one connected worker in this session."""

    worker_id: str
    name: str
    address: str
    first_seen: float
    last_seen: float
    gpus: list[dict] = field(default_factory=list)
    busy_lines: int = 0
    done: int = 0
    failed: int = 0
    version: str = ""
    accepts_updates: bool = False
    update_requested: bool = False
    update_status: str = ""
    mode: str = "run"  # run | stop (standby, connected) | shutdown (asked to close)
    progress: dict = field(default_factory=dict)  # current job: id, engine, lines, done, current line
    session: str = ""  # changes every time the worker program starts
    features: list = field(default_factory=list)  # e.g. ["stop", "shutdown"] – older workers send nothing
    exit_reason: str = ""  # why the worker program ended (sent when it closes); "" while it runs
    exit_at: float = 0.0
    work_started: float = 0.0  # first job handed out since start / Reset: the speed is measured from here


MODES = ("run", "stop", "shutdown")


class WorkerRegistry:
    """Thread-safe table of workers seen since the coordinator started, plus the global pause switch."""

    def __init__(self, max_batch: int = 16):
        self._lock = threading.Lock()
        self._workers: dict[str, WorkerState] = {}
        self.max_batch = max_batch
        self.paused = False

    def set_mode(self, worker_id: str, mode: str) -> bool:
        """Stop (standby), resume or shut down one worker; False when the worker is unknown."""
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        with self._lock:
            w = self._workers.get(worker_id)
            if w is None or (mode != "run" and mode not in w.features):
                return False  # unknown, or an older worker that would not react
            w.mode = mode
            return True

    def may_claim(self, worker_id: str) -> bool:
        """New work only when rendering is not paused and this worker is not stopped."""
        with self._lock:
            w = self._workers.get(worker_id)
            return not self.paused and (w is None or w.mode == "run")

    def commands(self, worker_id: str) -> dict:
        """What the heartbeat answer tells a worker: cancel its current job, shut down."""
        with self._lock:
            w = self._workers.get(worker_id)
            mode = w.mode if w else "run"
        return {"cancel": mode in ("stop", "shutdown"), "shutdown": mode == "shutdown", "paused": self.paused}

    def seen(self, worker_id: str, name: str, address: str, gpus: list[dict], busy_lines: int,
             version: str = "", accepts_updates: bool = False, update_status: str = "",
             progress: dict | None = None, session: str = "", features: list | None = None) -> bool:
        """Record a heartbeat; returns True when the worker should update itself now."""
        now = time.time()
        with self._lock:
            w = self._workers.get(worker_id)
            if w is None:
                w = self._workers[worker_id] = WorkerState(worker_id, name, address, now, now)
            if session and session != w.session:  # the worker program (re)started: a shutdown is over
                if w.session and w.mode == "shutdown":
                    w.mode = "run"
                w.session = session[:64]
            w.features = [f for f in (features or []) if f in ("stop", "shutdown")]
            w.exit_reason = ""  # it is running (again)
            p = progress if isinstance(progress, dict) else {}
            w.progress = {**{k: p[k][:120] for k in ("id", "engine", "current", "phase") if isinstance(p.get(k), str)},
                          **{k: p[k] for k in ("lines", "done") if type(p.get(k)) is int},
                          **({"models_gb": float(p["models_gb"])} if type(p.get("models_gb")) in (int, float) else {})}
            if w.version and version and version != w.version:
                w.update_requested = False  # it came back with a new version: done
            w.name, w.address, w.last_seen, w.gpus, w.busy_lines = name[:64], address, now, gpus[:8], busy_lines
            if busy_lines and not w.work_started:  # it claimed a job before its first heartbeat reached us
                w.work_started = now
            w.version, w.accepts_updates, w.update_status = version[:32], accepts_updates, update_status[:200]
            if update_status.startswith("failed"):
                w.update_requested = False
            return w.update_requested and accepts_updates

    def goodbye(self, worker_id: str, reason: str) -> None:
        """The worker program is closing: remember why, and show it as offline right away."""
        with self._lock:
            w = self._workers.get(worker_id)
            if w is not None:
                w.exit_reason = reason[:200] or "closed"
                w.exit_at = time.time()
                w.last_seen = w.exit_at - OFFLINE_AFTER_SECONDS - 1  # offline at once
                w.busy_lines, w.progress = 0, {}
                if w.mode == "shutdown":
                    w.mode = "run"  # the shutdown is done; a restart works normally

    def request_update(self) -> list[str]:
        """Ask every online worker that allows it to update itself; returns their names."""
        now = time.time()
        names = []
        with self._lock:
            for w in self._workers.values():
                if w.accepts_updates and now - w.last_seen < OFFLINE_AFTER_SECONDS:
                    w.update_requested = True
                    w.update_status = "update requested"
                    names.append(w.name)
        return names

    def started_job(self, worker_id: str) -> None:
        """A job was handed out: start the speed clock if it is not running (idle time does not count)."""
        with self._lock:
            w = self._workers.get(worker_id)
            if w is not None and not w.work_started:
                w.work_started = time.time()

    def record(self, worker_id: str, done: int, failed: int) -> None:
        """Count finished lines for the speed estimate."""
        with self._lock:
            w = self._workers.get(worker_id)
            if w is not None:
                w.done += done
                w.failed += failed

    def forget(self, worker_id: str) -> None:
        """Drop a worker from the live table (e.g. after revoking it)."""
        with self._lock:
            self._workers.pop(worker_id, None)

    def batch_size(self, requested: int) -> int:
        """Lines per job: what the worker asks for (it knows its VRAM), capped by the coordinator."""
        return max(1, min(requested, self.max_batch))

    def reset_speed(self) -> None:
        """Progress reset in the watcher: per-worker done / failed / lines per minute start from zero."""
        now = time.time()
        with self._lock:
            for w in self._workers.values():
                w.done, w.failed, w.first_seen, w.work_started = 0, 0, now, 0.0

    def snapshot(self) -> list[dict]:
        """Workers for the watcher, with online flag and lines per minute."""
        now = time.time()
        out = []
        with self._lock:
            for w in self._workers.values():
                d = asdict(w)
                d["online"] = now - w.last_seen < OFFLINE_AFTER_SECONDS
                d["last_contact"] = time.strftime("%H:%M", time.localtime(w.exit_at if w.exit_reason else w.last_seen))
                # speed since the first job (model loading and idle time before it do not count); lines already
                # finished inside the running batch count too, so the estimate does not jump batch by batch
                in_batch = w.progress.get("done", 0) if w.busy_lines else 0
                finished = w.done + w.failed + in_batch
                minutes = (w.last_seen - w.work_started) / 60 if w.work_started else 0
                d["lines_per_min"] = round(finished / minutes, 1) if minutes > 0.5 and finished else 0.0
                out.append(d)
        return sorted(out, key=lambda d: d["name"])
