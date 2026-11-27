"""Breeze engine: per-line settings, its reference voice, and when a worker cannot run it."""

from pathlib import Path

from voicecrucible.engines import breeze
from voicecrucible.lethalfantasy import build, emotions, profile as profile_mod

PROFILE = profile_mod.load(Path(__file__).parent / "data" / "profile")  # invented names


def test_breeze_params_use_the_long_direction():
    d = {"scene": "She holds him close.", "intent": "Comfort.", "subtext": "Afraid.", "delivery": "soft, shaky",
         "pace": "slow", "avoid": "NOT cheerful"}
    p = emotions.breeze(PROFILE, "Mira", "Angry", d)
    for part in ("She holds him close.", "Intent: Comfort.", "Subtext: Afraid.", "Facial expression: Angry",
                 "Delivery: soft, shaky, pace slow", "Avoid: NOT cheerful"):
        assert part in p["instruction"]
    assert p["cfg_scale"] == 3.25 and p["ref_text"] == PROFILE.reference_text
    plain = emotions.breeze(PROFILE, "Mira", "Angry", None)
    assert plain["instruction"].startswith("Facial expression: Angry")


def test_breeze_has_no_fallback_voice(tmp_path):
    no_text = profile_mod.Profile(PROFILE.folder, PROFILE.characters, PROFILE.expressions, PROFILE.emotions,
                                  PROFILE.lexicon, PROFILE.sounds, reference_text="")
    assert build.reference_voice(no_text, "Mira", "breeze") is None  # never the Chatterbox clip: wrong transcript
    assert build.reference_voice(no_text, "Mira", "chatterbox") is not None


def test_cannot_run_without_component(tmp_path, monkeypatch):
    monkeypatch.setenv(breeze.ENV_DIR, str(tmp_path))
    assert breeze.cannot_run() == "component not installed"


def test_short_lines_get_a_short_breeze_instruction():
    from types import SimpleNamespace
    from voicecrucible.lethalfantasy import emotions
    profile = SimpleNamespace(emotions={"sanitize": []}, expressions={}, lexicon=None, reference_text="")
    text = emotions.breeze_short_instruction(profile, "Happy", {"scene": "A long scene text", "delivery": "gleeful",
                                                                "avoid": "NOT angry"})
    assert "gleeful" in text and "NOT angry" in text and "A long scene text" not in text and "English" in text
