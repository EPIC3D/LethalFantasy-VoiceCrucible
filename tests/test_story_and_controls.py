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
    page = tmp_path / "voices" / "en" / "STORY" / "PAGE_1.ogg"
    page.write_bytes(b"edited by hand")
    assert story.join_pages(tmp_path, "en", CFG, parts) == ([], {})  # an existing page is kept
    assert page.read_bytes() == b"edited by hand"
    assert story.join_pages(tmp_path, "en", CFG, parts, replace=True)[0] == ["PAGE_1"]
    assert page.with_name("PAGE_1.bak.ogg").read_bytes() == b"edited by hand" and page.read_bytes() != b"edited by hand"


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



def test_watcher_refuses_foreign_host_header():
    from voicecrucible.watcher.server import is_local_host
    assert is_local_host("127.0.0.1:5132", 5132) and is_local_host("LOCALHOST:5132", 5132)
    assert not is_local_host("evil.example:5132", 5132) and not is_local_host(None, 5132)
    assert not is_local_host("127.0.0.1:80", 5132)


def test_watcher_form_becomes_safe_crucible_arguments(tmp_path):
    import pytest

    from voicecrucible.watcher.tasks import TaskError, build_args
    export = tmp_path / "LFTTS-export"
    export.mkdir()
    engines = ["chatterbox", "qwen"]
    with pytest.raises(TaskError, match="english_lines"):
        build_args({"action": "render", "lines": str(export)}, engines)
    (export / "english_lines.jsonl").write_text("")
    args = build_args({"action": "dry-run", "lines": str(export), "engine": "qwen", "only": "AKIPO_", "limit": 5,
                       "all": True}, engines)
    assert args == ["render", "--lines", str(export.resolve()), "--engine", "qwen", "--only", "AKIPO_",
                    "--limit", "5", "--all", "--dry-run"]
    assert build_args({"action": "story-join", "lines": str(export)}, engines)[-1] == "--join"
    assert build_args({"action": "retry-failed"}, engines) == ["render", "--retry-failed"]
    for bad in ({"action": "render", "lines": str(export), "engine": "evil"},
                {"action": "render", "lines": str(export), "only": "A --all"},
                {"action": "render", "lines": str(export), "limit": -1},
                {"action": "setup"}, {"action": "render", "lines": str(tmp_path / "nope")}):
        with pytest.raises(TaskError):
            build_args(bad, engines)


def test_watcher_profiles_select_copy_and_refuse_unknown(tmp_path):
    import shutil
    from types import SimpleNamespace

    import pytest

    from voicecrucible.core.config import Config
    from voicecrucible.watcher.server import Controls
    from voicecrucible.watcher.tasks import TaskError
    repo = Path(__file__).parents[1] / "profiles"
    for name in ("template", "lethalfantasy"):
        shutil.copytree(repo / name, tmp_path / "profiles" / name)
    cfg = Config(base_dir=tmp_path)
    state = SimpleNamespace(profile="lethalfantasy", check_settings={})
    c = Controls(cfg, 5130, tmp_path / "profiles" / "lethalfantasy", root=tmp_path)
    names = {p["name"]: p for p in c.status()["profiles"]}
    assert names["lethalfantasy"]["bundled"] and names["lethalfantasy"]["missing"] == 0
    c.action("/api/profile-new", {"name": "mine", "source": "lethalfantasy"}, state)
    assert state.profile == "mine" and c.status()["profile"] == "mine" and not c.status()["bundled"]
    assert c.memory.load()["profile"] == "mine"  # remembered for the next start
    again = Controls(cfg, 5130, tmp_path / "profiles" / "lethalfantasy", root=tmp_path)
    assert again.profile_folder.name == "mine"
    for bad in ({"name": "../../x"}, {"name": "nope"}):
        with pytest.raises(TaskError):
            c.action("/api/profile-select", bad, state)
    with pytest.raises(TaskError):
        c.action("/api/profile-import", {"file": str(tmp_path / "x.txt")}, state)


def test_loading_phase_and_model_folder_size_reach_the_watcher():
    r = WorkerRegistry(4)
    r.seen("w1", "PC", "127.0.0.1", [], 0, progress={"engine": "chatterbox", "lines": 16, "done": 0,
                                                            "phase": "loading", "models_gb": 2.13, "evil": "x"})
    p = r.snapshot()[0]["progress"]
    assert p["phase"] == "loading" and p["models_gb"] == 2.13 and "evil" not in p


def test_rendering_again_keeps_the_previous_file(tmp_path):
    from voicecrucible.coordinator import results
    line = Line(key="AKIPO_X", character="AKIPO", text="hi")
    first = results.save(tmp_path, "en", line, "ogg", b"edited by hand")
    results.save(tmp_path, "en", line, "ogg", b"new take")
    assert first.read_bytes() == b"new take" and first.with_name("AKIPO_X.bak.ogg").read_bytes() == b"edited by hand"


def test_output_folder_inside_the_game_is_refused(tmp_path):
    import pytest

    from voicecrucible.core import config
    f = tmp_path / "voicecrucible.toml"
    f.write_text('[paths]\noutput_dir = "D:/Games/LethalFantasy/BepInEx/plugins/LethalFantasyTTS"\n')
    with pytest.raises(config.ConfigError, match="BepInEx"):
        config.load(f)
    f.write_text('[paths]\noutput_dir = "output"\n')
    config.load(f)


def test_render_clock_is_kept_in_the_queue(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite")
    assert q.run_times() == (None, None)
    q.add("test", [Line(key=f"K{i}", character="C", text="t") for i in range(2)])
    start, end = q.run_times()
    assert start and end is None
    job = q.claim("w", 5)
    for ln in job.lines:
        q.finish(job.job_id, ln.uid, True)
    q.close()
    s2, e2 = JobQueue(tmp_path / "q.sqlite").run_times()  # survives a restart
    assert s2 == start and e2 is not None and e2 >= start


def test_cancel_render_removes_waiting_lines_and_stops_their_workers(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite")
    q.add("test", [Line(key=f"K{i}", character="C", text="t") for i in range(5)])
    job = q.claim("w", 2)
    q.finish(job.job_id, job.lines[0].uid, True)
    assert q.cancel() == 4  # 1 still rendering + 3 waiting; the finished one stays
    assert q.counts() == {"pending": 0, "leased": 0, "done": 1, "failed": 0}
    assert job.job_id in q.cancelled_jobs  # the heartbeat tells this worker to stop
    assert q.finish(job.job_id, job.lines[1].uid, True) is None  # its late result is ignored


def test_unfinished_render_starts_paused(tmp_path):
    from types import SimpleNamespace

    from voicecrucible.coordinator.run import hold_leftover
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite")
    state = SimpleNamespace(queue=q, registry=WorkerRegistry(4), leftover=None)
    hold_leftover(state)
    assert not state.registry.paused and state.leftover is None  # empty queue: nothing to hold
    q.add("test", [Line(key="K1", character="C", text="t")])
    hold_leftover(state)
    assert state.registry.paused and state.leftover["lines"] == 1 and state.leftover["since"]


def test_voice_pack_folder_can_be_changed_in_the_watcher(tmp_path):
    import shutil
    from types import SimpleNamespace

    import pytest

    from voicecrucible.core.config import Config
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.watcher.server import Controls
    from voicecrucible.watcher.tasks import TaskError, build_args
    shutil.copytree(Path(__file__).parents[1] / "profiles" / "lethalfantasy", tmp_path / "profiles" / "lethalfantasy")
    cfg = Config(base_dir=tmp_path)
    q = JobQueue(tmp_path / "q.sqlite")
    state = SimpleNamespace(queue=q, output_root=cfg.path("output"), profile="lethalfantasy", check_settings={})
    c = Controls(cfg, 5130, tmp_path / "profiles" / "lethalfantasy", root=tmp_path)
    target = tmp_path / "packs" / "mine"
    c.action("/api/output-select", {"folder": str(target)}, state)
    assert state.output_root == target and target.is_dir() and c.memory.load()["output"] == str(target)
    with pytest.raises(TaskError, match="BepInEx"):
        c.action("/api/output-select", {"folder": str(tmp_path / "Game" / "BepInEx" / "plugins")}, state)
    q.add("test", [Line(key="K", character="C", text="t")])
    with pytest.raises(TaskError, match="still waiting"):
        c.action("/api/output-select", {"folder": str(tmp_path / "other")}, state)
    export = tmp_path / "exp"
    export.mkdir()
    (export / "english_lines.jsonl").write_text("")
    args = build_args({"action": "render", "lines": str(export)}, ["chatterbox"], "lethalfantasy", str(target))
    assert args[-2:] == ["--output", str(target)] and build_args({"action": "retry-failed"}, [], "", "x") == \
        ["render", "--retry-failed"]


def test_problem_lines_point_to_their_take(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("test", [Line(key="K", character="C", text="t")])
    job = q.claim("w", 1)
    take = str(tmp_path / "takes" / "1_a1.ogg")
    q.finish(job.job_id, job.lines[0].uid, False, reason="words differ", take=take, score=3.0)
    p = q.recent_problems()[0]
    assert p["has_audio"] and q.problem_audio(p["uid"]) == ("", take)
    assert q.problem_audio(999) == ("", "")


def test_problem_line_can_be_accepted_by_hand(tmp_path):
    from types import SimpleNamespace

    from voicecrucible.core.queue import JobQueue
    from voicecrucible.watcher.server import _accept
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("test", [Line(key="K", character="C", text="t"), Line(key="L", character="C", text="t")])
    job = q.claim("w", 2)
    takes = tmp_path / "takes"
    takes.mkdir()
    (takes / "1_a1.ogg").write_bytes(b"take")
    q.finish(job.job_id, job.lines[0].uid, False, reason="other voice", take=str(takes / "1_a1.ogg"), score=3.0)
    state = SimpleNamespace(queue=q, output_root=tmp_path / "out", language="en", takes_dir=takes)
    uid = q.recent_problems()[0]["uid"]
    assert _accept(state, uid)[0] == 200
    assert q.recent_problems() == [] and q.counts()["done"] == 1
    assert (tmp_path / "out" / "voices" / "en" / "C" / "K.ogg").read_bytes() == b"take"  # exported
    assert _accept(state, job.lines[1].uid)[0] == 404  # still rendering, no take: refused
    assert _accept(state, "1")[0] == 400


def test_retry_failed_renders_new_takes_not_the_same_ones(tmp_path):
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.engines.base import seed_for
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=2)
    q.add("test", [Line(key="K", character="C", text="t")])
    seeds = []
    for _ in range(2):  # two takes, both fail -> failed for good
        job = q.claim("w", 1)
        seeds.append(seed_for(job.lines[0]))
        q.finish(job.job_id, job.lines[0].uid, False, reason="bad")
    assert q.counts()["failed"] == 1 and q.retry_failed() == 1
    job = q.claim("w", 1)
    assert job.lines[0].attempt == 3 and seed_for(job.lines[0]) not in seeds  # take 3: a new seed, a new take


def test_export_summary_counts_lines_speakers_and_emotions(tmp_path):
    import json

    import pytest

    from voicecrucible.watcher.tasks import TaskError, export_info
    with pytest.raises(TaskError):
        export_info(str(tmp_path))
    (tmp_path / "english_lines.jsonl").write_text('{"key": "A", "text": "a"}\n{"key": "B", "text": "b"}\n')
    events = [{"key": "A", "character": "Akipo", "type": "Normal", "expression": "Happy"},
              {"key": "B", "character": "RedTwin", "type": "Followup", "expression": "Angry"},
              {"key": "B", "character": "RedTwin", "type": "Followup", "expression": "Angry"}]
    (tmp_path / "dialogue_events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\nbroken\n")
    i = export_info(str(tmp_path))
    assert i["texts"] == 2 and i["dialogue_lines"] == 2 and i["speakers"] == {"RedTwin": 2, "Akipo": 1}
    assert i["expressions"] == {"Angry": 2, "Happy": 1} and i["has_events"]


def test_render_again_updates_queued_lines_and_short_lines_are_steadier(tmp_path):
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.engines.chatterbox import steady_short_line
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("test", [Line(key="K", character="C", text='"Mhm"')])
    job = q.claim("w", 1)
    q.finish(job.job_id, job.lines[0].uid, False, reason="gibberish")
    assert q.add("test", [Line(key="K", character="C", text='"Mm-hmm"')]) == 0  # normal render: skipped
    assert q.add("test", [Line(key="K", character="C", text='"Mm-hmm"')], again=True) == 1  # render again
    again = q.claim("w", 1).lines[0]
    assert again.text == '"Mm-hmm"' and again.attempt == 2  # new text, new take
    assert steady_short_line('"Definitely"', 0.7, 0.4) == (0.5, 0.5)
    assert steady_short_line("You know what that means, don't you?", 0.7, 0.4) == (0.7, 0.4)


def test_skipped_part_is_left_out_of_the_page(tmp_path):
    from types import SimpleNamespace

    from voicecrucible.coordinator import results
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.watcher.server import _skip
    parts = [Line(key="PAGE_1__p001", character=story.PARTS_FOLDER, text="a", emotion="Narrator"),
             Line(key="PAGE_1__p002", character=story.PARTS_FOLDER, text='"Mm-hmm"', emotion="Red")]
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("chatterbox", parts)
    job = q.claim("w", 2)
    tone = (0.1 * np.sin(np.arange(24000) / 10)).astype(np.float32)
    results.save(tmp_path, "en", job.lines[0], "ogg", audio.encode(tone, 24000))
    q.finish(job.job_id, job.lines[0].uid, True)
    bad = results.save(tmp_path, "en", job.lines[1], "ogg", b"noise")  # an exported best take
    q.finish(job.job_id, job.lines[1].uid, False, reason="not human")
    q.set_output(job.lines[1].uid, bad.relative_to(tmp_path).as_posix())
    state = SimpleNamespace(queue=q, output_root=tmp_path)
    assert _skip(state, job.lines[1].uid)[0] == 200
    assert not bad.exists() and bad.with_name("PAGE_1__p002.skipped.ogg").exists()  # renamed, not deleted
    assert q.recent_problems() == [] and q.skipped_keys() == {"PAGE_1__p002"}
    joined, missing = story.join_pages(tmp_path, "en", CFG, parts, skipped=q.skipped_keys())
    assert joined == ["PAGE_1"] and not missing


def test_skip_plays_the_profiles_skip_sound_when_there_is_one(tmp_path):
    from types import SimpleNamespace

    from voicecrucible.core.queue import JobQueue
    from voicecrucible.watcher.server import _skip
    profile = tmp_path / "myprofile"
    (profile / "voices").mkdir(parents=True)
    tone = (0.1 * np.sin(np.arange(8000) / 3)).astype(np.float32)
    (profile / "voices" / "skip_sound.ogg").write_bytes(audio.encode(tone, 16000))  # e.g. crickets
    part = Line(key="PAGE_1__p002", character=story.PARTS_FOLDER, text='"Mm-hmm"', emotion="Red")
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("chatterbox", [part])
    job = q.claim("w", 1)
    q.finish(job.job_id, job.lines[0].uid, False, reason="not human")
    state = SimpleNamespace(queue=q, output_root=tmp_path / "out", language="en", profile=str(profile))
    assert _skip(state, job.lines[0].uid)[1]["sound"] == "skip_sound.ogg"
    assert (tmp_path / "out" / "voices" / "en" / story.PARTS_FOLDER / "PAGE_1__p002.ogg").exists()
    assert q.skipped_keys() == set()  # it has a file now: the audiobook join uses it


def test_render_again_of_a_passed_line_makes_a_new_take(tmp_path):
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.engines.base import seed_for
    q = JobQueue(tmp_path / "q.sqlite")
    q.add("test", [Line(key="K", character="C", text="Get her Lena!")])
    job = q.claim("w", 1)
    first = seed_for(job.lines[0])
    q.finish(job.job_id, job.lines[0].uid, True)  # passed on take 1
    assert q.add("test", [Line(key="K", character="C", text="Get her Lena!")], again=True) == 1
    again = q.claim("w", 1).lines[0]
    assert again.attempt == 2 and seed_for(again) != first  # heard: the same take came back before


def test_finished_lines_can_be_found_heard_and_redone(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite")
    q.add("test", [Line(key="STATUE_5__he", character="RED", text="Get him Lena!"),
                   Line(key="OTHER", character="RED", text="Hello")])
    job = q.claim("w", 2)
    for ln in job.lines:
        q.finish(job.job_id, ln.uid, True, output=f"voices/en/RED/{ln.key}.ogg")
    assert [x["key"] for x in q.finished("lena")] == ["STATUE_5__he"]  # search by text, any case
    hit = q.finished("STATUE")[0]
    assert hit["take"] == 1 and q.problem_audio(hit["uid"])[0] == "voices/en/RED/STATUE_5__he.ogg"
    assert q.redo(hit["uid"]).key == "STATUE_5__he"
    assert q.claim("w", 5).lines[0].attempt == 2  # a new take
    assert q.redo(hit["uid"]) is None  # it is rendering now


def test_a_passed_take_that_sounds_wrong_can_be_skipped(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite")
    q.add("test", [Line(key="TWINS_TEASER_12__p002", character="_STORY_PARTS", text='"Definitely"')])
    job = q.claim("w", 1)
    q.finish(job.job_id, job.lines[0].uid, True, output="voices/en/_STORY_PARTS/TWINS_TEASER_12__p002.ogg")
    line, output = q.skip(job.lines[0].uid)  # heard: passed after 18 takes, but not good
    assert output.endswith("p002.ogg") and q.skipped_keys() == {"TWINS_TEASER_12__p002"}
    assert q.finished() == []


def test_recheck_imports_a_pack_and_finds_lines_to_check(tmp_path):
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.lethalfantasy.recheck import _find
    from voicecrucible.watcher.tasks import build_args
    pack = tmp_path / "game" / "voices" / "en" / "RED"
    pack.mkdir(parents=True)
    (pack / "STATUE_5__he.ogg").write_bytes(b"x")
    assert _find(tmp_path / "game", "en", "RED", "STATUE_5__he") == pack / "STATUE_5__he.ogg"
    assert _find(tmp_path / "game" / "voices" / "en", "en", "RED", "STATUE_5__he") is not None
    q = JobQueue(tmp_path / "q.sqlite")
    line = Line(key="STATUE_5", character="RED", text="Get him Lena!", variant="he")
    assert q.record_existing("chatterbox", [(line, "voices/en/RED/STATUE_5__he.ogg")]) == 1
    (done, output), = q.done_lines("STATUE")
    q.mark_problem(done.uid, "words: words differ – heard: 'Kill him, Lena'")
    p = q.recent_problems()[0]
    assert p["reason"].startswith("re-check:") and p["has_audio"]  # listen, Accept, Redo or Skip in the watcher
    export = tmp_path / "exp"
    export.mkdir()
    (export / "english_lines.jsonl").write_text("")
    args = build_args({"action": "recheck", "source": str(tmp_path / "game"), "lines": str(export), "only": "BLUE"}, [])
    assert args[:3] == ["recheck", "--only", "BLUE"] and "--from" in args and "--lines" in args


def test_recheck_from_a_folder_checks_that_folders_file(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    line = Line(key="STATUE_5", character="RED", text="Get him Lena!", variant="he")
    q.add("chatterbox", [line])
    job = q.claim("w", 1)
    q.finish(job.job_id, job.lines[0].uid, False, reason="other voice")  # in Problems already
    assert q.done_lines() == []
    assert q.record_existing("chatterbox", [(line, "voices/en/RED/STATUE_5__he.ogg")]) == 1
    assert [ln.key for ln, _ in q.done_lines()] == ["STATUE_5"]  # heard: "no finished lines to check" before


def test_recheck_accepts_a_character_folder(tmp_path):
    from voicecrucible.lethalfantasy.recheck import _find
    akipo = tmp_path / "voices" / "en" / "AKIPO"
    akipo.mkdir(parents=True)
    (akipo / "AKIPO_X.ogg").write_bytes(b"x")
    assert _find(akipo, "en", "AKIPO", "AKIPO_X") == akipo / "AKIPO_X.ogg"
    assert _find(akipo, "en", "RED", "BLUETWIN_Y") is None  # a Red line is not in Akipo's folder


def test_long_task_can_be_paused_and_stopped_from_the_watcher(tmp_path):
    from voicecrucible.core.config import Config
    from voicecrucible.watcher.tasks import TaskRunner, read_control
    cfg = Config(base_dir=tmp_path)
    runner = TaskRunner(cfg)
    runner.control({"pause": True, "stop": False})
    assert read_control(cfg) == {"pause": True, "stop": False}
    runner.control({"pause": False, "stop": True})
    assert read_control(cfg)["stop"] and not read_control(cfg)["pause"]


def test_progress_reset_counts_from_zero_but_deletes_nothing(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("test", [Line(key=f"K{i}", character="C", text="t") for i in range(4)])
    job = q.claim("w", 2)
    q.finish(job.job_id, job.lines[0].uid, True)
    q.finish(job.job_id, job.lines[1].uid, False, reason="bad")
    assert q.progress_counts() == {"pending": 2, "leased": 0, "done": 1, "failed": 1}
    q.reset_progress()
    assert q.progress_counts() == {"pending": 2, "leased": 0, "done": 0, "failed": 0}
    assert q.counts()["done"] == 1 and len(q.recent_problems()) == 1  # nothing deleted
    job = q.claim("w", 1)
    q.finish(job.job_id, job.lines[0].uid, True)
    assert q.progress_counts()["done"] == 1 and q.run_times()[0] is not None


def test_retry_only_the_problems_shown(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("test", [Line(key=f"K{i}", character="C", text="t") for i in range(3)])
    job = q.claim("w", 3)
    for ln in job.lines:
        q.finish(job.job_id, ln.uid, False, reason="bad")
    shown = [job.lines[2].uid]  # the others were hidden with "Clear list"
    assert q.retry_failed(shown) == 1 and q.counts() == {"pending": 1, "leased": 0, "done": 0, "failed": 2}
    assert q.retry_failed() == 2  # the Render panel's button: all of them


def test_takes_per_line_can_be_set_in_the_watcher(tmp_path):
    import shutil
    from types import SimpleNamespace

    import pytest

    from voicecrucible.core.config import Config
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.watcher.server import Controls
    from voicecrucible.watcher.tasks import TaskError
    shutil.copytree(Path(__file__).parents[1] / "profiles" / "lethalfantasy", tmp_path / "profiles" / "lethalfantasy")
    cfg = Config(base_dir=tmp_path)
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=3)
    state = SimpleNamespace(queue=q)
    c = Controls(cfg, 5130, tmp_path / "profiles" / "lethalfantasy", root=tmp_path)
    c.action("/api/takes", {"takes": 6}, state)
    assert q.max_attempts == 6
    q.add("test", [Line(key="K", character="C", text="t")])
    for _ in range(5):  # 5 failed takes: still waiting for the 6th
        job = q.claim("w", 1)
        q.finish(job.job_id, job.lines[0].uid, False, reason="bad")
    assert q.counts()["pending"] == 1
    q2 = JobQueue(tmp_path / "q2.sqlite", max_attempts=3)
    c.restore_takes(SimpleNamespace(queue=q2))
    assert q2.max_attempts == 6  # remembered for the next start
    with pytest.raises(TaskError):
        c.action("/api/takes", {"takes": 11}, state)


def test_after_redo_keep_new_or_restore_old(tmp_path):
    from types import SimpleNamespace

    from voicecrucible.coordinator import results
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.watcher.server import _choose_version, _line_files
    q = JobQueue(tmp_path / "q.sqlite")
    line = Line(key="K", character="RED", text="Get him Lena!")
    q.add("test", [line])
    job = q.claim("w", 1)
    first = results.save(tmp_path, "en", job.lines[0], "ogg", b"old take")
    q.finish(job.job_id, job.lines[0].uid, True, output=first.relative_to(tmp_path).as_posix())
    uid = job.lines[0].uid
    q.redo(uid)
    job = q.claim("w", 1)
    results.save(tmp_path, "en", job.lines[0], "ogg", b"new take")  # the earlier one becomes K.bak.ogg
    state = SimpleNamespace(queue=q, output_root=tmp_path)
    current, old = _line_files(state, uid)
    assert current.read_bytes() == b"new take" and old.read_bytes() == b"old take"
    assert _choose_version(state, uid, restore_old=True)[0] == 200  # swap: nothing lost
    assert current.read_bytes() == b"old take" and old.read_bytes() == b"new take"
    assert _choose_version(state, uid, restore_old=False)[0] == 200  # keep what is current now, drop the other
    assert current.read_bytes() == b"old take" and not old.exists()
    assert _choose_version(state, uid, restore_old=False)[0] == 404


def test_hover_context_shows_expression_and_neighbour_lines(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("test", [Line(key=f"RED_ANGRY_FIRST_{i}", character="RED", text=f"line {i}", emotion="Angry",
                        params={"exaggeration": 0.7}) for i in (1, 2, 10)])
    job = q.claim("w", 3)
    q.finish(job.job_id, job.lines[1].uid, False, reason="bad")
    c = q.recent_problems()[0]["context"]
    assert c["emotion"] == "Angry" and c["params"] == {"exaggeration": 0.7}
    assert c["prev"] == "line 1" and c["next"] == "line 10"  # natural order: 2 comes before 10


def test_redo_settings_are_for_one_round_only(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=2)
    q.add("test", [Line(key="K", character="RED", text="Get him Lena!", params={"exaggeration": 0.7, "cfg_weight": 0.4})])
    job = q.claim("w", 1)
    q.finish(job.job_id, job.lines[0].uid, True, output="voices/en/RED/K.ogg")
    uid = job.lines[0].uid
    q.redo(uid, {"exaggeration": 0.55})
    job = q.claim("w", 1)
    assert job.lines[0].params == {"exaggeration": 0.55, "cfg_weight": 0.4}  # this round
    q.finish(job.job_id, uid, False, reason="bad")
    job = q.claim("w", 1)
    assert job.lines[0].params["exaggeration"] == 0.55  # still this round (take 2 of 2)
    q.finish(job.job_id, uid, True, output="voices/en/RED/K.ogg")
    q.redo(uid)
    assert q.claim("w", 1).lines[0].params == {"exaggeration": 0.7, "cfg_weight": 0.4}  # its own settings again


def test_trim_cuts_a_bad_start_and_keeps_the_old_version(tmp_path):
    from types import SimpleNamespace

    from voicecrucible.coordinator import results
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.watcher.server import _trim
    sr = 24000
    gurgle = (0.3 * np.random.default_rng(1).standard_normal(int(0.2 * sr))).astype(np.float32)
    speech = (0.5 * np.sin(np.arange(sr) / 8)).astype(np.float32)
    take = np.concatenate([gurgle, np.zeros(int(0.15 * sr), np.float32), speech])
    q = JobQueue(tmp_path / "q.sqlite")
    q.add("test", [Line(key="K", character="RED", text="Get him Lena!")])
    job = q.claim("w", 1)
    f = results.save(tmp_path, "en", job.lines[0], "ogg", audio.encode(take, sr))
    q.finish(job.job_id, job.lines[0].uid, True, output=f.relative_to(tmp_path).as_posix())
    state = SimpleNamespace(queue=q, output_root=tmp_path)
    info = _trim(state, job.lines[0].uid, None)[1]
    assert len(info["envelope"]) == 135 and info["duration_ms"] == 1350
    assert _trim(state, job.lines[0].uid, 300)[0] == 200  # cut the gurgle (0-200 ms) and the gap
    y, _ = audio.decode(f.read_bytes())
    assert abs(len(y) / sr - (1.35 - 0.3 + audio.LEAD_IN_SECONDS)) < 0.02
    assert f.with_name("K.bak.ogg").exists()  # the version before the cut
    assert _trim(state, job.lines[0].uid, 99999)[0] == 400


def test_insert_a_pause_between_sentences(tmp_path):
    from types import SimpleNamespace

    from voicecrucible.coordinator import results
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.watcher.server import _insert_pause
    sr = 24000
    take = (0.5 * np.sin(np.arange(2 * sr) / 8)).astype(np.float32)
    q = JobQueue(tmp_path / "q.sqlite")
    q.add("test", [Line(key="K", character="AKIPO", text="One. Two.")])
    job = q.claim("w", 1)
    f = results.save(tmp_path, "en", job.lines[0], "ogg", audio.encode(take, sr))
    q.finish(job.job_id, job.lines[0].uid, True, output=f.relative_to(tmp_path).as_posix())
    state = SimpleNamespace(queue=q, output_root=tmp_path)
    assert _insert_pause(state, job.lines[0].uid, 1000, 500)[0] == 200
    y, _ = audio.decode(f.read_bytes())
    assert abs(len(y) / sr - 2.5) < 0.02 and np.abs(y[int(1.1 * sr):int(1.4 * sr)]).max() < 0.01  # the silence
    assert f.with_name("K.bak.ogg").exists()
    assert _insert_pause(state, job.lines[0].uid, 1000, 9000)[0] == 400



def test_redo_with_free_text_for_one_round(tmp_path):
    from voicecrucible.core.queue import JobQueue
    from voicecrucible.engines.base import spoken_text
    q = JobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.add("test", [Line(key="K", character="AKIPO", text="So tiny!", params={"exaggeration": 0.5})])
    job = q.claim("w", 1)
    q.finish(job.job_id, job.lines[0].uid, True, output="voices/en/AKIPO/K.ogg")
    q.redo(job.lines[0].uid, {"spoken_text": "Sooo tiny!"})
    line = q.claim("w", 1).lines[0]
    assert line.text == "So tiny!" and spoken_text(line) == "Sooo tiny!"  # the subtitle text stays


def test_recheck_from_the_game_again_keeps_your_fixed_version(tmp_path):
    from voicecrucible.core.queue import JobQueue
    q = JobQueue(tmp_path / "q.sqlite")
    line = Line(key="AKIPO_HOUSE_2_1", character="AKIPO", text="So tiny...")
    q.record_existing("chatterbox", [(line, "voices/en/AKIPO/AKIPO_HOUSE_2_1.ogg")])  # imported from the game
    assert q.made_here() == set()  # the game's file: a later import may replace it
    (done, _), = q.done_lines()
    q.redo(done.uid, {"spoken_text": "Oh my, so tiny!"})
    job = q.claim("w", 1)
    q.finish(job.job_id, done.uid, True, output="voices/en/AKIPO/AKIPO_HOUSE_2_1.ogg")  # fixed in Voice Crucible
    assert q.made_here() == {("AKIPO_HOUSE_2_1", "AKIPO", "")}  # a re-check from the game keeps this one
