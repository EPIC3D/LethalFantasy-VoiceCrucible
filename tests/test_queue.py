"""Tests for the SQLite job queue: leases, retries, expiry."""

import time

from voicecrucible.core.jobs import Line
from voicecrucible.core.queue import JobQueue


def _queue(tmp_path, **kw):
    q = JobQueue(tmp_path / "q.sqlite", **kw)
    q.add("test", [Line(key=f"K{i}", character="MIRA", text="hi") for i in range(5)])
    return q


def test_add_skips_duplicates(tmp_path):
    q = _queue(tmp_path)
    assert q.add("test", [Line(key="K0", character="MIRA", text="hi"), Line(key="K9", character="MIRA", text="x")]) == 1
    assert q.counts()["pending"] == 6


def test_claim_and_finish(tmp_path):
    q = _queue(tmp_path)
    job = q.claim("w1", 3)
    assert len(job.lines) == 3 and q.counts()["leased"] == 3
    assert q.leased_line(job.job_id, job.lines[0].uid, "w2") is None  # other worker
    assert q.finish(job.job_id, job.lines[0].uid, True, output="a.wav") == "done"
    assert q.finish(job.job_id, job.lines[0].uid, True) is None  # already done
    assert q.counts()["done"] == 1


def test_failed_line_retries_then_fails(tmp_path):
    q = _queue(tmp_path, max_attempts=2)
    for _ in range(2):
        job = q.claim("w1", 1)
        assert job.lines[0].key == "K0"
        q.finish(job.job_id, job.lines[0].uid, False, reason="silent")
    assert q.counts()["failed"] == 1
    assert q.recent_problems()[0]["reason"] == "silent"


def test_best_failed_take_is_remembered(tmp_path):
    q = _queue(tmp_path, max_attempts=2)
    job = q.claim("w1", 1)
    assert q.finish(job.job_id, job.lines[0].uid, False, "noisy", take="t1.ogg", score=2.5) == "pending"
    job = q.claim("w1", 1)
    assert q.finish(job.job_id, job.lines[0].uid, False, "other voice", take="t2.ogg", score=1.5) == "failed"
    assert q.best_take(job.lines[0].uid) == "t1.ogg"  # higher quality wins


def test_retry_failed_gives_fresh_attempts(tmp_path):
    q = _queue(tmp_path, max_attempts=1)
    job = q.claim("w1", 1)
    q.finish(job.job_id, job.lines[0].uid, False, "broken")
    assert q.counts()["failed"] == 1 and q.retry_failed() == 1
    again = q.claim("w1", 1)  # fresh attempts, but take 2 (a new seed – take 1 would sound exactly the same)
    assert q.counts()["failed"] == 0 and again.lines[0].attempt == 2
    q.finish(again.job_id, again.lines[0].uid, False, "broken")
    assert q.counts()["failed"] == 1  # max_attempts counts per round again


def test_release_without_counting(tmp_path):
    q = _queue(tmp_path, max_attempts=1)
    job = q.claim("w1", 5)
    assert q.release(job.job_id, "w2", "x", count_attempt=False) == 0  # not its lease
    assert q.release(job.job_id, "w1", "stopped", count_attempt=False) == 5
    assert q.counts()["pending"] == 5


def test_restarted_worker_gets_its_old_lines_back_without_penalty(tmp_path):
    q = _queue(tmp_path, max_attempts=1)
    q.claim("w1", 2)  # worker crashed with these
    job = q.claim("w1", 5)  # same worker after restart
    assert len(job.lines) == 5 and q.counts()["leased"] == 5 and q.counts()["failed"] == 0


def test_lost_worker_lease_expires_and_heartbeat_extends(tmp_path):
    q = _queue(tmp_path, lease_seconds=1.0)  # generous margins: timing tests must not be flaky on slow machines
    job = q.claim("alive", 1)
    q.claim("lost", 1)
    time.sleep(0.6)
    q.touch("alive", job.job_id)
    time.sleep(0.6)
    assert q.expire() == 1
    assert q.counts() == {"pending": 4, "leased": 1, "done": 0, "failed": 0}


def test_claim_skips_engines_the_worker_cannot_run(tmp_path):
    q = JobQueue(tmp_path / "q.sqlite")
    q.add("breeze", [Line(key="B0", character="MIRA", text="hi")])
    q.add("chatterbox", [Line(key="C0", character="MIRA", text="hi")])
    small = q.claim("small_gpu", 4, frozenset({"breeze"}))
    assert small.engine == "chatterbox" and [ln.key for ln in small.lines] == ["C0"]
    q.finish(small.job_id, small.lines[0].uid, True, output="c0.ogg")
    assert q.claim("small_gpu", 4, frozenset({"breeze"})) is None  # the breeze line waits for a big worker
    assert q.claim("big_gpu", 4).engine == "breeze"


def test_uid_search():
    from voicecrucible.core.queue import _uid_query
    assert _uid_query(" #1234 ") == 1234
    assert _uid_query("1234") is None and _uid_query("#abc") is None


def test_redo_after_a_failed_recheck_gives_a_new_take(tmp_path):
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.core.jobs import Line
    q = JobQueue(tmp_path / "q.sqlite")
    q.add("test", [Line(key="K", character="A", text="Hello there")])
    uid = q._db.execute("SELECT uid FROM lines").fetchone()[0]
    q._db.execute("UPDATE lines SET status = 'failed', attempts = 0 WHERE uid = ?", (uid,))
    before = q._db.execute("SELECT takes_before FROM lines WHERE uid = ?", (uid,)).fetchone()[0]
    q.redo(uid)
    assert q._db.execute("SELECT takes_before FROM lines WHERE uid = ?", (uid,)).fetchone()[0] == before + 1
