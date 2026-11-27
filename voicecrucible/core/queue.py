"""Persistent job queue in SQLite: lines wait, are leased to a worker, and end up done or failed.

A lease expires when a worker disappears (no heartbeat); its lines go back to the queue. A failed line is
retried until `max_attempts`; every failure keeps its reason so it can be shown and reported.
"""

from __future__ import annotations

import json
import re
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
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v REAL);
"""
_ADDED_COLUMNS = {"best_take": "TEXT NOT NULL DEFAULT ''", "best_score": "REAL NOT NULL DEFAULT -1",
                  # takes of earlier rounds (Retry failed): the next take numbers – and seeds – continue after them,
                  # so a retried line does not render the very same take again
                  "takes_before": "INTEGER NOT NULL DEFAULT 0",
                  "skipped": "INTEGER NOT NULL DEFAULT 0",  # done without a voice (Skip in the watcher)
                  "finished_at": "REAL NOT NULL DEFAULT 0",  # when the line was done (finished-lines list)
                  "params_saved": "TEXT NOT NULL DEFAULT ''"}  # a one-round Redo's settings: the line's own ones

STATUSES = ("pending", "leased", "done", "failed")
_LINE_COLUMNS = "uid, key, character, variant, text, emotion, direction, voice, params, attempts, takes_before"


def _line(r: tuple) -> Line:
    """Build a Line from a row selected with _LINE_COLUMNS."""
    return Line(key=r[1], character=r[2], variant=r[3], text=r[4], emotion=r[5], direction=r[6], uid=r[0],
                voice=r[7], params=json.loads(r[8]), attempt=r[10] + r[9] + 1)


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
        self.cancelled_jobs: set[str] = set()  # leases removed by cancel(): their workers are told to stop
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def close(self) -> None:
        """Close the database file."""
        self._db.close()

    def add(self, engine: str, lines: list[Line], again: bool = False) -> int:
        """Queue lines for an engine; lines already queued for that engine are skipped. Returns the number added.

        `again` (render --all): lines already in the queue are queued once more with their new text and settings
        (e.g. after a pronunciation or profile change); their next takes get new seeds. Lines rendering right now
        are left alone."""
        rows = [(ln.key, ln.character, ln.variant, ln.text, ln.emotion, ln.direction, ln.voice, json.dumps(ln.params),
                 engine) for ln in lines]
        with self._lock:
            before, idle = self._count_locked(), self._remaining_locked() == 0
            changes_before = self._db.total_changes
            if again:
                self._db.executemany(
                    "INSERT INTO lines (key, character, variant, text, emotion, direction, voice, params, engine)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (key, character, variant, engine) DO UPDATE SET"
                    " text = excluded.text, emotion = excluded.emotion, direction = excluded.direction,"
                    " voice = excluded.voice, params = excluded.params, status = 'pending',"
                    # a passed line used one more take than its failed attempts: skip that one too
                    " takes_before = takes_before + attempts + (CASE WHEN status = 'done' THEN 1 ELSE 0 END),"
                    " attempts = 0, reason = '', output = '',"
                    " best_take = '', best_score = -1, skipped = 0 WHERE status != 'leased'", rows)
                added = self._db.total_changes - changes_before
            else:
                self._db.executemany("INSERT OR IGNORE INTO lines (key, character, variant, text, emotion, direction,"
                                     " voice, params, engine) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
                added = self._count_locked() - before
            if added and idle:
                self._new_run_locked()
            return added

    def claim(self, worker: str, max_lines: int, skip_engines: frozenset[str] = frozenset()) -> Job | None:
        """Lease up to `max_lines` pending lines of one engine to a worker; None when nothing is pending.
        `skip_engines`: engines this worker cannot run (e.g. too little VRAM) – their lines wait for another worker."""
        with self._lock:
            self._expire_locked()
            # a worker works on one job at a time: anything it still holds is left over from before a restart
            orphans = [r[0] for r in self._db.execute(
                "SELECT uid FROM lines WHERE worker = ? AND status = 'leased'", (worker,))]
            self._requeue_locked(orphans, "", count_attempt=False)
            skip = sorted(skip_engines)
            not_in = f" AND engine NOT IN ({','.join('?' * len(skip))})" if skip else ""
            first = self._db.execute(f"SELECT engine FROM lines WHERE status = 'pending'{not_in} ORDER BY uid LIMIT 1",
                                     skip).fetchone()
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
            self._set_meta_locked("last_finish", time.time())
            if passed:
                self._db.execute("UPDATE lines SET status = 'done', output = ?, reason = '', lease_id = NULL,"
                                 " lease_until = NULL, finished_at = ? WHERE uid = ?", (output, time.time(), uid))
                self._restore_params_locked(uid)
                return "done"
            if take and score > held[0]:
                self._db.execute("UPDATE lines SET best_take = ?, best_score = ? WHERE uid = ?", (take, score, uid))
            self._requeue_locked([uid], reason, count_attempt=True)
            status = self._db.execute("SELECT status FROM lines WHERE uid = ?", (uid,)).fetchone()[0]
            if status == "failed":
                self._restore_params_locked(uid)
            return status

    def retry_failed(self, uids: list[int] | None = None) -> int:
        """Put the lines that failed for good back into the queue with fresh attempts – all of them, or only `uids`
        (the ones the watcher shows). Returns how many."""
        where = "status = 'failed'" + (f" AND uid IN ({','.join('?' * len(uids))})" if uids is not None else "")
        with self._lock:
            idle = self._remaining_locked() == 0
            cur = self._db.execute("UPDATE lines SET status = 'pending', takes_before = takes_before + attempts,"
                                   " attempts = 0, reason = '', output = '', best_take = '', best_score = -1"
                                   f" WHERE {where}", [int(u) for u in uids or []])
            if cur.rowcount and idle:
                self._new_run_locked()
            return cur.rowcount

    def run_times(self) -> tuple[float | None, float | None]:
        """(start, end) of the current render: lines added to an empty queue start it; end = last result once
        nothing is waiting or rendering any more (None while it runs). Kept in the queue file, so it survives restarts."""
        with self._lock:
            meta = dict(self._db.execute("SELECT k, v FROM meta").fetchall())
            start = meta.get("run_start")
            if start is None:
                return None, None
            if self._remaining_locked():
                return start, None
            last = meta.get("last_finish")
            return start, last if last is not None and last >= start else start

    def _remaining_locked(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM lines WHERE status IN ('pending', 'leased')").fetchone()[0]

    def _set_meta_locked(self, key: str, value: float) -> None:
        self._db.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (key, value))

    def _new_run_locked(self) -> None:
        self._set_meta_locked("run_start", time.time())
        self._db.execute("DELETE FROM meta WHERE k = 'last_finish'")

    def best_take(self, uid: int) -> str:
        """Stored file of the best failed take of a line ('' if none)."""
        with self._lock:
            r = self._db.execute("SELECT best_take FROM lines WHERE uid = ?", (uid,)).fetchone()
        return r[0] if r else ""

    def accept(self, uid: int) -> Line | None:
        """Accept a problem line by hand (its take was heard and is fine): mark it done and drop its failure reason.
        Only lines that failed for good or wait for a retry and have a take; returns the line (None if refused)."""
        with self._lock:
            r = self._db.execute(f"SELECT {_LINE_COLUMNS} FROM lines WHERE uid = ? AND status IN ('failed', 'pending')"
                                 " AND reason != '' AND (output != '' OR best_take != '')", (uid,)).fetchone()
            if r is None:
                return None
            self._db.execute("UPDATE lines SET status = 'done', reason = '', lease_id = NULL, lease_until = NULL,"
                             " finished_at = ? WHERE uid = ?", (time.time(), uid))
            return _line(r)

    def skip(self, uid: int) -> tuple[Line, str] | None:
        """Leave a problem line without a voice (it cannot be spoken well, e.g. a hum): done, no file. Returns the
        line and its exported output path (to be moved away), or None when refused (rendering right now)."""
        with self._lock:
            # a problem line, or a finished one whose take passed the checks but sounds wrong (heard by ear)
            r = self._db.execute(f"SELECT {_LINE_COLUMNS}, output FROM lines WHERE uid = ?"
                                 " AND (status = 'done' OR (status IN ('failed', 'pending') AND reason != ''))",
                                 (uid,)).fetchone()
            if r is None:
                return None
            self._db.execute("UPDATE lines SET status = 'done', reason = '', output = '', skipped = 1,"
                             " lease_id = NULL, lease_until = NULL WHERE uid = ?", (uid,))
            return _line(r[:-1]), r[-1]

    def mark_spoken(self, uid: int, output: str) -> None:
        """A skipped line got a file after all (the profile's skip sound): done with this output, not skipped."""
        with self._lock:
            self._db.execute("UPDATE lines SET skipped = 0, output = ? WHERE uid = ?", (output, uid))

    def skipped_keys(self) -> set[str]:
        """Keys of the lines that were skipped (left without a voice)."""
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT key FROM lines WHERE skipped = 1")}

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

    def cancel(self) -> int:
        """Remove every line that is waiting or being rendered (a worker's late results for them are ignored).
        Finished and failed lines – and their voice files – are kept. Returns how many lines were removed."""
        with self._lock:
            self.cancelled_jobs |= {r[0] for r in self._db.execute(
                "SELECT DISTINCT lease_id FROM lines WHERE status = 'leased' AND lease_id IS NOT NULL")}
            cur = self._db.execute("DELETE FROM lines WHERE status IN ('pending', 'leased')")
            self._db.execute("DELETE FROM meta WHERE k = 'run_start'")
            return cur.rowcount

    def counts(self) -> dict[str, int]:
        """Number of lines per status."""
        with self._lock:
            found = dict(self._db.execute("SELECT status, COUNT(*) FROM lines GROUP BY status").fetchall())
        return {s: found.get(s, 0) for s in STATUSES}

    def progress_counts(self) -> dict[str, int]:
        """Counts for the watcher's progress: waiting and rendering lines, and the lines finished or failed since the
        last Reset (all of them without a reset)."""
        with self._lock:
            reset = dict(self._db.execute("SELECT k, v FROM meta").fetchall()).get("progress_reset", 0)
            found = dict(self._db.execute(
                "SELECT status, COUNT(*) FROM lines WHERE status IN ('pending', 'leased') OR finished_at > ?"
                " GROUP BY status", (reset,)).fetchall())
        return {s: found.get(s, 0) for s in STATUSES}

    def reset_progress(self) -> None:
        """Start the progress (counts, runtime, speed) from zero again – nothing is deleted."""
        with self._lock:
            now = time.time()
            self._set_meta_locked("progress_reset", now)
            time.sleep(0.002)  # every line finished from now on gets a later time stamp than the reset
            if self._remaining_locked():
                self._set_meta_locked("run_start", now)
            else:
                self._db.execute("DELETE FROM meta WHERE k IN ('run_start', 'last_finish')")

    def recent_problems(self, limit: int = 20, query: str = "") -> list[dict[str, str]]:
        """Lines with a failure reason (failed for good, or waiting for a retry), newest first. `query`: every word
        must be in the key (with its variant), character, text or reason – searches all problems, not only the newest."""
        where, args = "reason != ''", []
        if (uid := _uid_query(query)) is not None:  # "#1234": that line only
            where, args, query = where + " AND uid = ?", [uid], ""
        for word in query.lower().split():
            where += " AND lower(key || '__' || variant || ' ' || character || ' ' || text || ' ' || reason) LIKE ?"
            args.append(f"%{word}%")
        with self._lock:
            rows = self._db.execute("SELECT key, character, variant, status, attempts, reason, output, uid, best_take,"
                                    f" text FROM lines WHERE {where} ORDER BY uid DESC LIMIT ?",
                                    (*args, limit)).fetchall()
            return [{"key": r[0], "character": r[1], "variant": r[2], "status": r[3], "attempts": r[4], "reason": r[5],
                     "best_take_used": bool(r[6]), "uid": r[7], "has_audio": bool(r[6] or r[8]), "text": r[9],
                     "context": self._context_locked(r[7])} for r in rows]

    def _context_locked(self, uid: int) -> dict:
        """What helps judging a take: the expression, its engine settings and the lines before and after it in the
        same scene (same key group, e.g. ..._ANGRY_FIRST_1/_2/_3 or a page's parts; only lines in the queue)."""
        r = self._db.execute("SELECT key, variant, emotion, params FROM lines WHERE uid = ?", (uid,)).fetchone()
        if r is None:
            return {}
        key, variant, emotion, params = r
        group = key.rsplit("_", 1)[0] + "_"
        rows = self._db.execute("SELECT key, text FROM lines WHERE key LIKE ? AND variant = ? AND key != ?",
                                (group.replace("%", "") + "%", variant, key)).fetchall()
        rows = sorted(rows + [(key, None)], key=lambda kv: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", kv[0])])
        i = next(n for n, kv in enumerate(rows) if kv[0] == key)
        return {"emotion": emotion, "params": json.loads(params or "{}"),
                "prev": rows[i - 1][1] if i > 0 else "", "next": rows[i + 1][1] if i + 1 < len(rows) else ""}

    def record_existing(self, engine: str, found: list[tuple[Line, str]]) -> int:
        """Re-check from a folder: lines whose voice file was copied in from that folder are recorded as done with it
        (whatever they were before), so that very file is checked. Lines rendering right now are left alone."""
        rows = [(ln.key, ln.character, ln.variant, ln.text, ln.emotion, ln.direction, ln.voice, json.dumps(ln.params),
                 engine, out) for ln, out in found]
        with self._lock:
            before = self._db.total_changes
            self._db.executemany(
                "INSERT INTO lines (key, character, variant, text, emotion, direction, voice, params, engine, status,"
                " output, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'done', ?, 0)"
                " ON CONFLICT (key, character, variant, engine) DO UPDATE SET status = 'done', output = excluded.output,"
                " reason = '', skipped = 0 WHERE status != 'leased'", rows)
            return self._db.total_changes - before

    def made_here(self) -> set[tuple[str, str, str]]:
        """(key, character, variant) of the lines whose current file was rendered, accepted or edited in Voice Crucible
        – a re-check from a folder must not put the folder's older file over them."""
        with self._lock:
            return {(r[0], r[1], r[2]) for r in self._db.execute(
                "SELECT key, character, variant FROM lines WHERE finished_at > 0 AND output != ''")}

    def mark_edited(self, uid: int) -> None:
        """The line's file was changed in the watcher (trim, pause, restore): it counts as made here."""
        with self._lock:
            self._db.execute("UPDATE lines SET finished_at = ? WHERE uid = ?", (time.time(), uid))

    def done_lines(self, only: str = "") -> list[tuple[Line, str]]:
        """Finished lines with a voice file (and the file, relative to the output folder), optionally by key prefix."""
        with self._lock:
            rows = self._db.execute(f"SELECT {_LINE_COLUMNS}, output FROM lines WHERE status = 'done' AND output != ''"
                                    " AND key LIKE ? ORDER BY uid", (only.replace("%", "") + "%",)).fetchall()
        return [(_line(r[:-1]), r[-1]) for r in rows]

    def mark_problem(self, uid: int, reason: str) -> None:
        """A finished line failed a re-check: it goes to the problems (its file stays) for a listen and a decision."""
        with self._lock:
            self._db.execute("UPDATE lines SET status = 'failed', reason = ? WHERE uid = ? AND status = 'done'",
                             (f"re-check: {reason}"[:500], uid))

    def finished(self, query: str = "", limit: int = 50) -> list[dict]:
        """Finished lines with a voice file, newest first; `query` filters key or text (case-insensitive)."""
        like = f"%{query.strip()}%"
        uid = _uid_query(query)  # "#1234": that line only
        match, args = ("uid = ?", (uid,)) if uid is not None else ("(key LIKE ? OR text LIKE ?)", (like, like))
        with self._lock:
            rows = self._db.execute(
                "SELECT uid, key, character, variant, text, takes_before + attempts + 1, output, finished_at FROM lines"
                f" WHERE status = 'done' AND output != '' AND {match}"
                " ORDER BY finished_at DESC, uid DESC LIMIT ?", (*args, limit)).fetchall()
            return [{"uid": r[0], "key": r[1], "character": r[2], "variant": r[3], "text": r[4], "take": r[5],
                     "output": r[6], "finished_at": r[7] or None, "context": self._context_locked(r[0])} for r in rows]

    def redo(self, uid: int, once: dict | None = None) -> Line | None:
        """Render one finished (or failed) line again with a new take; None when it is waiting or rendering.
        `once`: engine settings for this round only (e.g. a lower exaggeration); afterwards the line's own come back."""
        with self._lock:
            r = self._db.execute(f"SELECT {_LINE_COLUMNS} FROM lines WHERE uid = ? AND status IN ('done', 'failed')",
                                 (uid,)).fetchone()
            if r is None:
                return None
            idle = self._remaining_locked() == 0
            # the next take must be a new one (its seed comes from the take number): a line that failed a re-check
            # has attempts = 0 and status 'failed' – counting nothing gave the same take again (heard: same voice)
            self._db.execute("UPDATE lines SET status = 'pending', takes_before = takes_before + attempts + 1,"
                             " attempts = 0, reason = '',"
                             " best_take = '', best_score = -1, skipped = 0 WHERE uid = ?", (uid,))
            if once:
                own = self._db.execute("SELECT params, params_saved FROM lines WHERE uid = ?", (uid,)).fetchone()
                saved = own[1] or own[0]  # a second Redo with settings keeps the line's own, not the first override
                self._db.execute("UPDATE lines SET params_saved = ?, params = ? WHERE uid = ?",
                                 (saved, json.dumps({**json.loads(saved or "{}"), **once}), uid))
            if idle:
                self._new_run_locked()
            return _line(r)

    def _restore_params_locked(self, uid: int) -> None:
        """The one-round settings of a Redo are used up: the line gets its own settings back."""
        self._db.execute("UPDATE lines SET params = params_saved, params_saved = '' WHERE uid = ? AND params_saved != ''",
                         (uid,))

    def problem_audio(self, uid: int) -> tuple[str, str]:
        """(exported output path relative to the output folder, best failed take path) of one line."""
        with self._lock:
            r = self._db.execute("SELECT output, best_take FROM lines WHERE uid = ?", (uid,)).fetchone()
        return ("", "") if r is None else (r[0], r[1])

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
            " finished_at = CASE WHEN attempts + ? >= ? THEN ? ELSE finished_at END,"
            " status = CASE WHEN attempts + ? >= ? THEN 'failed' ELSE 'pending' END WHERE uid = ?",
            [(inc, reason, inc, self.max_attempts, time.time(), inc, self.max_attempts, uid) for uid in uids])


def _uid_query(query: str) -> int | None:
    """The line ID of a search like "#1234" (the ID the watcher shows), else None."""
    q = query.strip()
    return int(q[1:]) if q.startswith("#") and q[1:].isdigit() else None
