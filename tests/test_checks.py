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


def test_installed_extras_detects_components():
    from voicecrucible.installer import update
    extras = update.installed_extras()
    assert isinstance(extras, list) and set(extras) <= {"gpu", "checks", "chatterbox", "qwen"}


def test_runner_encodes_passed_take_as_ogg():
    res = Runner("cpu").render(Job("j", "test", [Line(key="K", character="MIRA", text="hi", uid=1)]))
    assert res[0].passed and res[0].ext == "ogg" and res[0].audio[:4] == b"OggS"


def test_candidate_resamples_once():
    c = checks_base.Candidate(Line(key="K", character="A", text="x"), np.zeros(48000, np.float32), 48000)
    assert len(c.audio16k) == 16000 and c.audio16k is c.audio16k


def test_respelled_name_heard_correctly_passes():
    names = {"seleena": "sel", "solahna": "sol", "akeepo": "aki"}
    r = compare("Seleena added.", "Selena added.", names)  # failed before: 'sel' was compared with 'selena'
    assert r["ratio"] == 1.0 and r["names_ok"] and r["first_ok"]
    assert compare("Solahna coos.", "Solana coos.", names)["ratio"] == 1.0
    assert compare("Mhm", "We're a good life.", names)["ratio"] < 0.5  # real gibberish still fails


def test_interjections_become_speakable():
    from voicecrucible.textprep import prepare
    assert prepare('"Mhm"') == '"Mm-hmm"'
    assert prepare("Hm. Uhhuh, sure.") == "Hmm. Uh-huh, sure."
    assert prepare("Hmmm, the mhmx shop") == "Hmmm, the mhmx shop"  # only whole known words



def test_weak_takes_of_short_lines_still_fail():
    # heard by the user: "Duh, definitely" for "Definitely" was a weak take, the check must keep rejecting it
    assert compare('"Definitely"', "Duh, definitely.", {})["ratio"] < 0.75


def test_interjection_spellings_only_for_english():
    from voicecrucible.textprep import prepare
    assert prepare("Mhm", language="en") == "Mm-hmm" and prepare("Mhm", language="de") == "Mhm"


def test_sounds_without_words_get_longer_takes_and_fitting_checks():
    from voicecrucible.checks.words import speechless
    from voicecrucible.engines.chatterbox import longer_sound
    assert speechless('"Mm-hmm"') and speechless("Hehehe~") and not speechless('"Definitely"')
    assert longer_sound('"Mm-hmm"', 1) == '"Mm-hmm"' and longer_sound('"Mm-hmm"', 2) == '"Mmm-hmmm..."'
    assert longer_sound("Ahh!", 3) == "Ahhhh..." and longer_sound("Definitely", 2) == "Definitely"


def test_hum_scores_heard_by_ear_pass_and_noise_fails():
    import numpy as np

    from voicecrucible.checks.base import Candidate
    from voicecrucible.checks.similarity import SimilarityCheck

    class Fixed(SimilarityCheck):  # voice prints replaced by fixed scores measured on real takes
        def __init__(self, score):
            super().__init__({"min_similarity": 0.80})
            self._score, self._refs = score, {"ref": np.array([1.0])}

        def _embed(self, samples16k):
            return np.array([self._score])

    def take(text):
        return Candidate(line=Line(key="K", character="C", text=text), samples=np.zeros(16000, np.float32),
                         sample_rate=16000, reference="ref")
    assert Fixed(0.62).run(take('"Mm-hmm"')).passed  # "a bit like brushing teeth, but good"
    assert not Fixed(0.43).run(take('"Mm-hmm"')).passed  # "like choking or gargling"
    assert not Fixed(0.62).run(take('"Definitely"')).passed  # words: the normal limits stay



def test_sounds_fall_back_to_the_profiles_phrase_on_the_last_take():
    from pathlib import Path

    from voicecrucible.engines.chatterbox import longer_sound
    from voicecrucible.textprep.fallback import SoundFallbacks
    f = SoundFallbacks.load(Path(__file__).parents[1] / "profiles" / "lethalfantasy" / "sound_fallbacks.json")
    assert f.find('"Mm-hmm"') == "Yes." and f.find("Hmm?") == "Yes?" and f.find("Hmm...") == "I wonder..."
    assert f.find("Hehehe~") == "That is funny!" and f.find("Ahhh!", "Glowing") == "Feels good..."
    assert f.find("Ahh!", "Hurt") == ""  # pain or shock: no phrase, only a longer sound
    assert [longer_sound('"Mm-hmm"', a, "Yes.") for a in (1, 2, 3)] == ['"Mm-hmm"', '"Mmm-hmmm..."', "Yes."]
    assert longer_sound("Ahh!", 3) == "Ahhhh..."
    assert compare('"Mm-hmm"', "Mmm hmm", {})["ratio"] == 1.0 and compare('"Mm-hmm"', "We're a good life.", {})["ratio"] == 0.0
