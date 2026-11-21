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


class WorkerRegistry:
    """Thread-safe table of workers seen since the coordinator started."""

    def __init__(self, max_batch: int = 16):
        self._lock = threading.Lock()
        self._workers: dict[str, WorkerState] = {}
        self.max_batch = max_batch

    def seen(self, worker_id: str, name: str, address: str, gpus: list[dict], busy_lines: int,
             version: str = "", accepts_updates: bool = False, update_status: str = "") -> bool:
        """Record a heartbeat; returns True when the worker should update itself now."""
        now = time.time()
        with self._lock:
            w = self._workers.get(worker_id)
            if w is None:
                w = self._workers[worker_id] = WorkerState(worker_id, name, address, now, now)
            if w.version and version and version != w.version:
                w.update_requested = False  # it came back with a new version: done
            w.name, w.address, w.last_seen, w.gpus, w.busy_lines = name[:64], address, now, gpus[:8], busy_lines
            w.version, w.accepts_updates, w.update_status = version[:32], accepts_updates, update_status[:200]
            if update_status.startswith("failed"):
                w.update_requested = False
            return w.update_requested and accepts_updates

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

    def snapshot(self) -> list[dict]:
        """Workers for the watcher, with online flag and lines per minute."""
        now = time.time()
        out = []
        with self._lock:
            for w in self._workers.values():
                d = asdict(w)
                minutes = max((w.last_seen - w.first_seen) / 60, 1 / 60)
                d["online"] = now - w.last_seen < OFFLINE_AFTER_SECONDS
                d["lines_per_min"] = round((w.done + w.failed) / minutes, 1)
                out.append(d)
        return sorted(out, key=lambda d: d["name"])
