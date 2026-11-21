"""Tests for the model-free parts of the checks and for failed takes in the runner."""

import numpy as np

from voicecrucible.checks import base as checks_base
from voicecrucible.checks.words import compare
from voicecrucible.core.jobs import CheckResult, Job, Line
from voicecrucible.worker.runner import Runner

NAMES = {"orrnehlla": "orn", "ornehlla": "orn", "nehll": "nel", "meerah": "mir"}


def test_name_inside_another_name_is_not_required():
    assert compare("Ornehlla, you would blow it", "Ornella, you would blow it", NAMES)["names_ok"]


def test_compare_accepts_fillers_and_inserted_interjection():
    r = compare("Get away from me!", "Ugh, get away from me.", {})
    assert r["ratio"] == 1.0 and r["first_ok"]
    r = compare("Get away from me!", "Oh no, get away from me.", {})
    assert r["first_ok"]  # "no" inserted before the line, line follows


def test_compare_detects_clipped_start_and_missing_name():
    assert not compare("Hello there friend", "there friend", {})["first_ok"]
    assert compare("Orrnehlla, come here", "Ornella, come here", NAMES)["names_ok"]
    assert not compare("Orrnehlla, come here", "Mira, come here", NAMES)["names_ok"]


def test_summary_lists_failed_checks():
    ok, reason = checks_base.summary([CheckResult("a", True), CheckResult("b", False, "too high")])
    assert not ok and reason == "b: too high"


class _AlwaysFail(checks_base.Check):
    name = "fail"

    def run(self, take):
        return CheckResult(self.name, False, "for the test")


def test_runner_reports_failed_take(monkeypatch):
    monkeypatch.setitem(checks_base._MODULES, "fail", __name__)
    monkeypatch.setattr(__import__(__name__), "CHECK", _AlwaysFail, raising=False)
    job = Job("j", "test", [Line(key="K", character="MIRA", text="hi", uid=1)], settings={"enabled": ["fail"]})
    res = Runner("cpu").render(job)
    assert not res[0].passed and res[0].reason == "fail: for the test"
    assert res[0].audio[:4] == b"OggS"  # failed takes are sent too: the best one is used if every attempt fails


def test_runner_encodes_passed_take_as_ogg():
    res = Runner("cpu").render(Job("j", "test", [Line(key="K", character="MIRA", text="hi", uid=1)]))
    assert res[0].passed and res[0].ext == "ogg" and res[0].audio[:4] == b"OggS"


def test_candidate_resamples_once():
    c = checks_base.Candidate(Line(key="K", character="A", text="x"), np.zeros(48000, np.float32), 48000)
    assert len(c.audio16k) == 16000 and c.audio16k is c.audio16k
