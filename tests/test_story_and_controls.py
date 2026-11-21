"""Tests for story mode (page splitting, joining) and the watcher controls (pause, stop, shutdown, cancel)."""

from pathlib import Path

import numpy as np

from voicecrucible.coordinator.scheduler import WorkerRegistry
from voicecrucible.core import audio
from voicecrucible.core.jobs import Job, Line
from voicecrucible.lethalfantasy import story
from voicecrucible.textprep.pronounce import Lexicon
from voicecrucible.worker.runner import Runner

CFG = story.StoryConfig(prefix="PAGE_", folder="STORY", narrator="Narrator",
                        colors={"red": "Red", "#00ffff": "Blue"},
                        voices={"Narrator": Path("n.wav"), "Red": Path("r.wav"), "Blue": Path("b.wav")},
                        params={"Red": {"exaggeration": 0.7}})


def test_split_page_by_colour():
    text = 'Intro. <color=red>"Hi!"</color> said Red.\n\n<color=#00FFFF>"Hello~"</color> <color=green>x</color> end'
    parts = story.split_page(text, CFG)
    # unknown colours (green) are read by the narrator; whitespace-only parts are dropped
    assert [s for s, _ in parts] == ["Narrator", "Red", "Narrator", "Blue", "Narrator", "Narrator"]


def test_build_lines_numbers_parts_and_splits_long_text(tmp_path):
    for name in ("n", "r", "b"):
        (tmp_path / f"{name}.wav").write_bytes(b"x")
    cfg = story.StoryConfig(**{**CFG.__dict__, "voices": {k: tmp_path / v for k, v in CFG.voices.items()}})
    long_text = " ".join(["This is a sentence."] * 40) + ' <color=red>"Hi!"</color>'
    lines = story.build_lines({"PAGE_2": long_text, "PAGE_1": "Short."}, cfg, Lexicon({}), lambda p: p.stem)
    assert lines[0].key == "PAGE_1__p001" and lines[1].key == "PAGE_2__p001"
    page2 = [ln for ln in lines if ln.key.startswith("PAGE_2")]
    assert len(page2) > 2 and all(len(ln.text) <= story.MAX_PART_CHARS for ln in page2)
    assert page2[-1].emotion == "Red" and page2[-1].voice == "r" and page2[-1].params == {"exaggeration": 0.7}


def test_join_pages_waits_for_all_parts(tmp_path):
    parts = [Line(key="PAGE_1__p001", character=story.PARTS_FOLDER, text="a", emotion="Narrator"),
             Line(key="PAGE_1__p002", character=story.PARTS_FOLDER, text="b", emotion="Red")]
    folder = tmp_path / "voices" / "en" / story.PARTS_FOLDER
    folder.mkdir(parents=True)
    tone = (0.1 * np.sin(np.arange(24000) / 10)).astype(np.float32)
    (folder / "PAGE_1__p001.ogg").write_bytes(audio.encode(tone, 24000))
    joined, missing = story.join_pages(tmp_path, "en", CFG, parts)
    assert not joined and missing == {"PAGE_1": ["PAGE_1__p002"]}
    (folder / "PAGE_1__p002.ogg").write_bytes(audio.encode(tone, 24000))
    joined, missing = story.join_pages(tmp_path, "en", CFG, parts)
    y, sr = audio.decode((tmp_path / "voices" / "en" / "STORY" / "PAGE_1.ogg").read_bytes())
    assert joined == ["PAGE_1"] and abs(len(y) / sr - (2 + story.PAUSE_SWITCH)) < 0.1


def test_long_ogg_does_not_crash():
    y = (0.1 * np.sin(np.arange(24000 * 120) / 10)).astype(np.float32)  # libsndfile crashed on this in one call
    back, sr = audio.decode(audio.encode(y, 24000))
    assert abs(len(back) / sr - 120) < 0.1


def test_pause_stop_and_shutdown_controls():
    r = WorkerRegistry()
    r.seen("old", "PC", "127.0.0.1", [], 0)  # an older worker sends no features
    assert not r.set_mode("old", "stop") and r.may_claim("old")  # so it can't be stopped (it would not react)
    r.seen("w1", "PC", "127.0.0.1", [], 0, features=["stop", "shutdown"])
    assert r.may_claim("w1") and r.commands("w1") == {"cancel": False, "shutdown": False, "paused": False}
    r.paused = True
    assert not r.may_claim("w1")
    r.paused = False
    assert r.set_mode("w1", "stop") and not r.may_claim("w1") and r.commands("w1")["cancel"]
    assert r.set_mode("w1", "run") and r.may_claim("w1")
    assert r.set_mode("w1", "shutdown") and r.commands("w1")["shutdown"]
    assert not r.set_mode("nobody", "stop")
    r.seen("w1", "PC", "127.0.0.1", [], 0, session="a", features=["stop", "shutdown"])
    r.set_mode("w1", "shutdown")
    r.seen("w1", "PC", "127.0.0.1", [], 0, session="a", features=["stop", "shutdown"])  # same program: still shutting down
    assert r.commands("w1")["shutdown"]
    r.seen("w1", "PC", "127.0.0.1", [], 0, session="b", features=["stop", "shutdown"])  # restarted on that PC: works again
    assert r.may_claim("w1") and not r.commands("w1")["shutdown"]


def test_goodbye_shows_why_a_worker_is_offline():
    r = WorkerRegistry()
    r.seen("w1", "PC", "127.0.0.1", [], 5, session="a", features=["stop", "shutdown"])
    r.set_mode("w1", "shutdown")
    r.goodbye("w1", "shut down from the watcher – start worker.cmd on that PC")
    w = r.snapshot()[0]
    assert not w["online"] and w["exit_reason"].startswith("shut down") and w["last_contact"] and w["busy_lines"] == 0
    r.seen("w1", "PC", "127.0.0.1", [], 0, session="b", features=["stop", "shutdown"])  # started again
    w = r.snapshot()[0]
    assert w["online"] and w["exit_reason"] == "" and w["mode"] == "run"


def test_runner_stops_between_lines_and_reports_progress():
    job = Job("j", "test", [Line(key=f"K{i}", character="A", text="hi", uid=i) for i in range(5)])
    runner = Runner("cpu", max_batch=1)
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) > 2  # stop before the third line

    results = runner.render(job, cancel=cancel)
    assert [t.uid for t in results] == [0, 1] and runner.progress["done"] == 2 and runner.progress["lines"] == 5
