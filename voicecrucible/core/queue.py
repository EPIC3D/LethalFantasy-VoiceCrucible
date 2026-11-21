"""Persistent job queue in SQLite: lines wait, are leased to a worker, and end up done or failed.

A lease expires when a worker disappears (no heartbeat); its lines go back to the queue. A failed line is
retried until `max_attempts`; every failure keeps its reason so it can be shown and reported.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from voicecrucible.core.jobs import Job, Line

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lines (
    uid INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL, character TEXT NOT NULL, variant TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL, emotion TEXT NOT NULL DEFAULT '', direction TEXT NOT NULL DEFAULT '',
    voice TEXT NOT NULL DEFAULT '', params TEXT NOT NULL DEFAULT '{}',
    engine TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_id TEXT, worker TEXT, lease_until REAL,
    reason TEXT NOT NULL DEFAULT '', output TEXT NOT NULL DEFAULT '',
    best_take TEXT NOT NULL DEFAULT '', best_score REAL NOT NULL DEFAULT -1,
    UNIQUE (key, character, variant, engine)
);
CREATE INDEX IF NOT EXISTS idx_lines_status ON lines (status);
"""
_ADDED_COLUMNS = {"best_take": "TEXT NOT NULL DEFAULT ''", "best_score": "REAL NOT NULL DEFAULT -1"}

STATUSES = ("pending", "leased", "done", "failed")
_LINE_COLUMNS = "uid, key, character, variant, text, emotion, direction, voice, params, attempts"


def _line(r: tuple) -> Line:
    """Build a Line from a row selected with _LINE_COLUMNS."""
    return Line(key=r[1], character=r[2], variant=r[3], text=r[4], emotion=r[5], direction=r[6], uid=r[0],
                voice=r[7], params=json.loads(r[8]), attempt=r[9] + 1)


class JobQueue:
    """Thread-safe queue of lines to render, stored in one SQLite file."""

    def __init__(self, db_path: Path, lease_seconds: float = 600, max_attempts: int = 3):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        have = {r[1] for r in self._db.execute("PRAGMA table_info(lines)")}
        for name, definition in _ADDED_COLUMNS.items():  # queues made by older versions
            if name not in have:
                self._db.execute(f"ALTER TABLE lines ADD COLUMN {name} {definition}")
        self._lock = threading.Lock()
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def close(self) -> None:
        """Close the database file."""
        self._db.close()

    def add(self, engine: str, lines: list[Line]) -> int:
        """Queue lines for an engine; lines already queued for that engine are skipped. Returns the number added."""
        rows = [(ln.key, ln.character, ln.variant, ln.text, ln.emotion, ln.direction, ln.voice, json.dumps(ln.params),
                 engine) for ln in lines]
        with self._lock:
            before = self._count_locked()
            self._db.executemany("INSERT OR IGNORE INTO lines (key, character, variant, text, emotion, direction, voice,"
                                 " params, engine) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            return self._count_locked() - before

    def claim(self, worker: str, max_lines: int) -> Job | None:
        """Lease up to `max_lines` pending lines of one engine to a worker; None when nothing is pending."""
        with self._lock:
            self._expire_locked()
            # a worker works on one job at a time: anything it still holds is left over from before a restart
            orphans = [r[0] for r in self._db.execute(
                "SELECT uid FROM lines WHERE worker = ? AND status = 'leased'", (worker,))]
            self._requeue_locked(orphans, "", count_attempt=False)
            first = self._db.execute("SELECT engine FROM lines WHERE status = 'pending' ORDER BY uid LIMIT 1").fetchone()
            if first is None:
                return None
            rows = self._db.execute(
                f"SELECT {_LINE_COLUMNS} FROM lines"
                " WHERE status = 'pending' AND engine = ? ORDER BY uid LIMIT ?", (first[0], max(1, max_lines))).fetchall()
            lease_id = uuid.uuid4().hex
            until = time.time() + self.lease_seconds
            self._db.executemany("UPDATE lines SET status = 'leased', lease_id = ?, worker = ?, lease_until = ? WHERE uid = ?",
                                 [(lease_id, worker, until, r[0]) for r in rows])
            lines = [_line(r) for r in rows]
            return Job(job_id=lease_id, engine=first[0], lines=lines, attempt=min(ln.attempt for ln in lines))

    def leased_line(self, lease_id: str, uid: int, worker: str) -> Line | None:
        """The line `uid` if this worker still holds it under this lease, else None (expired, finished, foreign)."""
        with self._lock:
            r = self._db.execute(f"SELECT {_LINE_COLUMNS} FROM lines"
                                 " WHERE uid = ? AND lease_id = ? AND worker = ? AND status = 'leased'",
                                 (uid, lease_id, worker)).fetchone()
        return None if r is None else _line(r)

    def voices(self) -> set[str]:
        """Asset IDs of all reference voices used by queued lines (the only assets workers may fetch)."""
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT DISTINCT voice FROM lines WHERE voice != ''")}

    def finish(self, lease_id: str, uid: int, passed: bool, reason: str = "", output: str = "",
               take: str = "", score: float = -1.0) -> str | None:
        """Record the result of one leased line; returns its new status, or None when the lease is not valid any more.

        A failed take with audio (`take` = stored file, `score` = its quality) is kept as a candidate: when the line
        runs out of attempts, the caller exports the best candidate (best_take()) as the line's output.
        """
        with self._lock:
            held = self._db.execute("SELECT best_score FROM lines WHERE uid = ? AND lease_id = ? AND status = 'leased'",
                                    (uid, lease_id)).fetchone()
            if held is None:
                return None
            if passed:
                self._db.execute("UPDATE lines SET status = 'done', output = ?, reason = '', lease_id = NULL,"
                                 " lease_until = NULL WHERE uid = ?", (output, uid))
                return "done"
            if take and score > held[0]:
                self._db.execute("UPDATE lines SET best_take = ?, best_score = ? WHERE uid = ?", (take, score, uid))
            self._requeue_locked([uid], reason, count_attempt=True)
            return self._db.execute("SELECT status FROM lines WHERE uid = ?", (uid,)).fetchone()[0]

    def best_take(self, uid: int) -> str:
        """Stored file of the best failed take of a line ('' if none)."""
        with self._lock:
            r = self._db.execute("SELECT best_take FROM lines WHERE uid = ?", (uid,)).fetchone()
        return r[0] if r else ""

    def set_output(self, uid: int, output: str) -> None:
        """Record the exported file of a line that failed every check (its best take)."""
        with self._lock:
            self._db.execute("UPDATE lines SET output = ? WHERE uid = ?", (output, uid))

    def release(self, lease_id: str, worker: str, reason: str, count_attempt: bool) -> int:
        """Give back every line the worker still holds under a lease. `count_attempt` = False when it just stopped."""
        with self._lock:
            uids = [r[0] for r in self._db.execute(
                "SELECT uid FROM lines WHERE lease_id = ? AND worker = ? AND status = 'leased'", (lease_id, worker))]
            self._requeue_locked(uids, reason, count_attempt)
            return len(uids)

    def touch(self, worker: str, lease_id: str) -> None:
        """Extend the lease the worker is working on right now (called on every heartbeat)."""
        with self._lock:
            self._db.execute("UPDATE lines SET lease_until = ? WHERE worker = ? AND lease_id = ? AND status = 'leased'",
                             (time.time() + self.lease_seconds, worker, lease_id))

    def expire(self) -> int:
        """Put lines of lost workers (lease ran out) back into the queue. Returns how many."""
        with self._lock:
            return self._expire_locked()

    def counts(self) -> dict[str, int]:
        """Number of lines per status."""
        with self._lock:
            found = dict(self._db.execute("SELECT status, COUNT(*) FROM lines GROUP BY status").fetchall())
        return {s: found.get(s, 0) for s in STATUSES}

    def recent_problems(self, limit: int = 20) -> list[dict[str, str]]:
        """Lines with a failure reason (failed for good, or waiting for a retry), newest first."""
        with self._lock:
            rows = self._db.execute("SELECT key, character, variant, status, attempts, reason, output FROM lines"
                                    " WHERE reason != '' ORDER BY uid DESC LIMIT ?", (limit,)).fetchall()
        return [{"key": r[0], "character": r[1], "variant": r[2], "status": r[3], "attempts": r[4], "reason": r[5],
                 "best_take_used": bool(r[6])} for r in rows]

    def _count_locked(self) -> int:
        """Total number of lines (caller holds the lock)."""
        return self._db.execute("SELECT COUNT(*) FROM lines").fetchone()[0]

    def _expire_locked(self) -> int:
        """Requeue lines whose lease ran out (caller holds the lock)."""
        uids = [r[0] for r in self._db.execute("SELECT uid FROM lines WHERE status = 'leased' AND lease_until < ?",
                                               (time.time(),))]
        self._requeue_locked(uids, "worker lost (lease expired)", count_attempt=True)
        return len(uids)

    def _requeue_locked(self, uids: list[int], reason: str, count_attempt: bool) -> None:
        """Back to 'pending', or to 'failed' once max_attempts is reached (caller holds the lock)."""
        inc = 1 if count_attempt else 0
        self._db.executemany(
            "UPDATE lines SET attempts = attempts + ?, reason = ?, lease_id = NULL, worker = NULL, lease_until = NULL,"
            " status = CASE WHEN attempts + ? >= ? THEN 'failed' ELSE 'pending' END WHERE uid = ?",
            [(inc, reason, inc, self.max_attempts, uid) for uid in uids])
