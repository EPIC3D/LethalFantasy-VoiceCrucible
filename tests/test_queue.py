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
    assert q.finish(job.job_id, job.lines[0].uid, True, output="a.wav")
    assert not q.finish(job.job_id, job.lines[0].uid, True)  # already done
    assert q.counts()["done"] == 1


def test_failed_line_retries_then_fails(tmp_path):
    q = _queue(tmp_path, max_attempts=2)
    for _ in range(2):
        job = q.claim("w1", 1)
        assert job.lines[0].key == "K0"
        q.finish(job.job_id, job.lines[0].uid, False, reason="silent")
    assert q.counts()["failed"] == 1
    assert q.recent_problems()[0]["reason"] == "silent"


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
    q = _queue(tmp_path, lease_seconds=0.2)
    job = q.claim("alive", 1)
    q.claim("lost", 1)
    time.sleep(0.15)
    q.touch("alive", job.job_id)
    time.sleep(0.1)
    assert q.expire() == 1
    assert q.counts() == {"pending": 4, "leased": 1, "done": 0, "failed": 0}
