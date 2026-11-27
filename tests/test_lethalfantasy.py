"""Tests for the LethalFantasy line builder and the directors (no models, no network)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from voicecrucible.directors import base as directions
from voicecrucible.directors.api import ApiDirector, ApiDirectorError, _first_json_object
from voicecrucible.directors.base import SceneLine
from voicecrucible.lethalfantasy import build, emotions, lines, naming, profile as profile_mod

PROFILE = profile_mod.load(Path(__file__).parent / "data" / "profile")  # invented names


def _export(tmp_path: Path) -> Path:
    texts = [("MIRA_DIALOGUE_X_1", "M-mommy? {They're} here~"), ("MIRA_DIALOGUE_X_Q", "Pick one"),
             ("VALE_DIALOGUE_Y_1_R", "Hehehe, Ornella~"), ("MIRA_DIALOGUE_EVENT_Z_1", "No event for me"),
             ("MIRA_DIALOGUE_X_2", "…"), ("MENU_START", "Start game")]
    (tmp_path / "english_lines.jsonl").write_text("\n".join(json.dumps({"key": k, "text": t}) for k, t in texts))
    events = [{"asset": "X", "event": 0, "line": 0, "key": "MIRA_DIALOGUE_X_1", "character": "Mira",
               "type": "Normal", "expression": "Angry"},
              {"asset": "Y", "event": 0, "line": 0, "key": "VALE_DIALOGUE_Y_1_R", "character": "Rook",
               "type": "Followup", "expression": "Smug"},
              {"asset": "X", "event": 1, "line": 0, "key": "MIRA_DIALOGUE_X_2", "character": "Mira",
               "type": "Normal", "expression": "Neutral"}]
    (tmp_path / "dialogue_events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    return tmp_path


def test_build_queue_lines(tmp_path):
    source = lines.read_export(_export(tmp_path), PROFILE)
    assert "MENU_START" not in {s.key for s in source}
    result = build.build(PROFILE, source, "chatterbox", {}, lambda p: "sha-" + p.stem)
    by_stem = {(ln.character, ln.file_stem): ln for ln in result.lines}
    # identity variants, stutter + name respelling, speaker from the event (Rook says a VALE key)
    assert by_stem[("MIRA", "MIRA_DIALOGUE_X_1__she")].text == "Mom... mommy? She's here"
    assert ("ROOK", "VALE_DIALOGUE_Y_1_R") in by_stem and by_stem[("ROOK", "VALE_DIALOGUE_Y_1_R")].voice == "sha-Rook"
    assert ("MIRA", "MIRA_DIALOGUE_EVENT_Z_1") in by_stem  # speaker from the key prefix
    assert by_stem[("MIRA", "MIRA_DIALOGUE_X_1__he")].params == {"exaggeration": 0.85, "cfg_weight": 0.35}
    assert result.skipped == {"never voiced (player choice / narration)": 1, "nothing to speak (only symbols)": 1}


def test_new_character_is_added_and_skipped_until_it_has_a_voice(tmp_path):
    import shutil
    prof = tmp_path / "profile"
    shutil.copytree(PROFILE.folder, prof, ignore=shutil.ignore_patterns("voices"))
    (tmp_path / "export").mkdir()
    export = _export(tmp_path / "export")
    with open(export / "dialogue_events.jsonl", "a") as f:
        f.write("\n" + json.dumps({"asset": "N", "key": "MIRA_DIALOGUE_X_1", "character": "Nova", "type": "Normal"}))
    assert profile_mod.add_new_characters(prof, lines.speakers(export)) == ["Nova"]
    p = profile_mod.load(prof)
    assert p.characters["Nova"].folder == "NV"  # from plugin_folders.json (default would be "NOVA")
    assert p.characters["Nova"].voices["chatterbox"].name == "Nova.wav"
    result = build.build(p, lines.read_export(export, p), "chatterbox", {}, lambda x: "id")
    assert result.missing_voices == {"Mira", "Rook", "Nova"} and not result.lines  # no voices in the copy


def test_other_language_texts_and_qwen_language(tmp_path):
    export = _export(tmp_path)
    (tmp_path / "hu.jsonl").write_text(json.dumps({"key": "MIRA_DIALOGUE_EVENT_Z_1", "text": "Szia, Ornella"}))
    source = lines.read_export(export, PROFILE, tmp_path / "hu.jsonl")
    assert [s.text for s in source] == ["Szia, Ornella"]
    res = build.build(PROFILE, lines.read_export(export, PROFILE), "qwen_vc", {}, lambda x: "id", language="ja")
    assert all(ln.params["language"] == "Japanese" for ln in res.lines)


def test_character_selection(tmp_path):
    source = lines.read_export(_export(tmp_path), PROFILE)
    result = build.build(PROFILE, source, "chatterbox", {}, lambda p: "x", characters=["ROOK"])
    assert {ln.character for ln in result.lines} == {"ROOK"}


def test_emotion_settings():
    assert emotions.chatterbox(PROFILE, "Vale", "Neutral") == {"exaggeration": 0.37, "cfg_weight": 0.55}
    assert emotions.chatterbox(PROFILE, "Vale", "Screaming")["exaggeration"] == 1.0  # Blue still yells
    q = emotions.qwen(PROFILE, "Mira", "Smile", {"scene": "S", "intent": "I", "subtext": "T",
                                                     "delivery": "with a giggle", "avoid": "NOT flat"})
    assert "soft nervous laugh" in q["instruct"] and "giggle" not in q["instruct"] and q["temperature"] == 0.6
    assert emotions.qwen(PROFILE, "Mira", "Angry", None)["temperature"] == 0.7


def test_identity_variants():
    assert naming.variants("plain") == [("", "plain")]
    assert [t for _, t in naming.variants("{They're} {them}")] == ["He's him", "She's her", "They're them"]


def test_directions_file_roundtrip(tmp_path):
    directions.save(tmp_path / "d.json", {"K": {"scene": "s", "delivery": "d", "extra": "dropped"}})
    assert directions.load(tmp_path / "d.json") == {"K": {"scene": "s", "intent": "", "subtext": "",
                                                          "delivery": "d", "avoid": "", "energy": "", "pace": ""}}


def test_direction_nudges_chatterbox():
    base = emotions.chatterbox(PROFILE, "Mira", "Angry")
    loud = emotions.chatterbox(PROFILE, "Mira", "Angry", {"energy": "5", "pace": "fast"})
    soft = emotions.chatterbox(PROFILE, "Mira", "Angry", {"energy": 1, "pace": "slow"})
    assert soft["exaggeration"] < base["exaggeration"] < loud["exaggeration"]
    assert soft["cfg_weight"] < base["cfg_weight"] < loud["cfg_weight"]
    assert emotions.chatterbox(PROFILE, "Mira", "Angry", {"energy": "?", "pace": "odd"}) == base  # junk is ignored


def test_first_json_object():
    assert _first_json_object('Sure!\n```json\n{"A": {"scene": "x"}}\n```') == {"A": {"scene": "x"}}
    with pytest.raises(ApiDirectorError):
        _first_json_object("no json here")


def test_api_director_against_fake_server(monkeypatch):
    seen = {}

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = {"choices": [{"message": {"content": json.dumps(
                {"K1": {"scene": "s", "delivery": "warm"}, "K_Q": {"scene": "player"}, "OTHER": {}})}}]}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()  # also answers the Ollama probe (GET -> 501)
    monkeypatch.setenv("TEST_KEY", "secret")
    d = ApiDirector(f"http://127.0.0.1:{server.server_address[1]}/v1", "m", "brief", "TEST_KEY")
    out = d.direct("scene", [SceneLine("K1", "Mira", "Hi", "Smile", True), SceneLine("K_Q", "PLAYER", "Yes", "", False)])
    server.shutdown()
    server.server_close()
    assert list(out) == ["K1"] and out["K1"]["delivery"] == "warm"  # only voiced lines of this scene
    assert seen["auth"] == "Bearer secret" and seen["body"]["messages"][0]["content"] == "brief"
    assert "[not voiced] K_Q" in seen["body"]["messages"][1]["content"]


def test_reward_notices_title_words_and_buttons_are_never_voiced():
    from voicecrucible.lethalfantasy import filters
    from voicecrucible.lethalfantasy.lines import SourceLine
    def voiced(key):
        return filters.is_voiced(SourceLine(key, "Akipo", "Normal", "Neutral", "x"))
    for key in ("AKIPO_DIALOGUE_EVENT_PET_RESPONSE_REWARD_GOD", "AKIPO_DIALOGUE_TITLE_MAIDEN_C",
                "AKIPO_DIALOGUE_TITLE_MOTHER_L", "AKIPO_DIALOGUE_EVENT_FMASSAGE_MINIGAME_STEP",
                "AKIPO_DIALOGUE_EVENT_NIGHTGOWN_CHOICE_2", "AKIPO_DIALOGUE_EVENT_FMASSAGE_MINIGAME_STEP_HARDER_MORE",
                "AKIPO_DIALOGUE_EVENT_FMASSAGE_MINIGAME_STOP"):
        assert not voiced(key), key
    for key in ("AKIPO_DIALOGUE_EVENT_FMASSAGE_MINIGAME_STEP_FIRSTTIME", "AKIPO_DIALOGUE_TITLE_RANDOM_1",
                "AKIPO_DIALOGUE_IDLE_TITLE_8"):
        assert voiced(key), key
