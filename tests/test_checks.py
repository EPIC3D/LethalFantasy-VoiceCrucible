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


def test_short_lines_fail_with_one_added_word():
    from voicecrucible.checks.words import SHORT_LINE_MATCH
    assert compare("Get them Lena!", "Get up them, Lena.", {})["ratio"] < SHORT_LINE_MATCH  # heard: a bad start
    assert compare("Get them Lena!", "Get them, Lena.", {})["ratio"] >= SHORT_LINE_MATCH
    assert compare('"Definitely"', "Duh, definitely.", {})["ratio"] < SHORT_LINE_MATCH


def test_drawn_out_words_match_the_word():
    assert compare("Ohh Soo tiny...", "Oh, so tiny.", {})["ratio"] == 1.0  # heard: rejected before ("Soo")
    assert compare("Sooo tiny!", "So tiny.", {})["ratio"] == 1.0
    assert compare("That is too good", "That is too good.", {})["ratio"] == 1.0
    assert compare("Get him Lena!", "Kittlin, Lena.", {})["ratio"] < 0.75  # real mistakes still fail


def test_primed_retake_is_cut_after_okay():
    import numpy as np

    from voicecrucible.core.jobs import Line
    from voicecrucible.worker import primer
    retake = Line(key="K", character="RED", text="Get him, Lena!", attempt=2)
    assert not primer.wants_primer(Line(key="K", character="RED", text="Get him, Lena!"))  # first take: plain
    assert primer.wants_primer(retake) and not primer.wants_primer(Line(key="H", character="RED", text="Mm-hmm", attempt=2))
    assert primer.primed(retake).params["spoken_text"] == "Okay... Get him, Lena!" and retake.params == {}
    times = [{"word": " Okay,", "start": 0.1, "end": 0.5}, {"word": " get", "start": 0.9, "end": 1.1}]
    assert primer.cut_point(np.zeros(48000, np.float32), 24000, times) == int(0.7 * 24000)
    sr = 24000  # no Whisper timing: the first pause after some sound
    y = np.concatenate([np.ones(int(0.3 * sr)), np.zeros(int(0.3 * sr)), np.ones(int(0.5 * sr))]).astype(np.float32)
    assert abs(primer.cut_point(y, sr, None) / sr - 0.45) < 0.02


def test_words_quote_marks_are_not_part_of_words():
    from voicecrucible.checks.words import compare, words
    assert words("She misspoke, it's 'be bigger'") == ["she", "mispoke", "it's", "be", "biger"]
    assert compare("She misspoke, it's 'be bigger'", "She misspoke. It's be bigger.", {})["ratio"] == 1.0
    assert words("'cause I said so") == ["because", "i", "said", "so"]


def test_strong_emotions_get_looser_limits():
    from voicecrucible.checks.base import limit
    from voicecrucible.core.jobs import Line
    s = {"min_similarity": 0.8, "intense_min_similarity": 0.62, "intense_expressions": ["Hurt", "Screaming"]}
    assert limit(s, Line(key="K", character="M", text="x", emotion="Hurt"), "min_similarity", 0.8) == 0.62
    assert limit(s, Line(key="K", character="M", text="x", emotion="Smile"), "min_similarity", 0.8) == 0.8
    assert limit({}, Line(key="K", character="M", text="x", emotion="Hurt"), "max_f0", 380.0) == 380.0  # old coordinator


def test_left_over_primer_okay_fails_the_first_word():
    from voicecrucible.checks.words import compare
    assert not compare("Not again", "Okay, not again", {})["first_ok"]
    assert compare("Okay, fine", "Okay, fine", {})["first_ok"]
    assert compare("Definitely", "Ugh, definitely", {})["first_ok"]


def test_jeez_and_geez_are_the_same_word():
    from voicecrucible.checks.words import compare
    r = compare("Jeez... sucks to be you little thing", "Geez, sucks to be you little thing.", {})
    assert r["first_ok"] and r["ratio"] == 1.0


def test_whisper_hint_only_has_the_names_of_the_line():
    from voicecrucible.checks.words import line_prompt
    names = {"solahna": "sol", "seleena": "sel", "lahna": "lan", "akeepo": "aki"}
    hint = "Akipo, Solana, Lana, Selena."
    assert line_prompt(hint, "Solahna!", names) == "Solana."
    assert line_prompt(hint, "Oh come on, Seleena", names) == "Selena."
    assert line_prompt(hint, "Nothing to see here", names) == ""


def test_a_line_can_carry_its_own_thresholds():
    from voicecrucible.checks.base import limit
    from voicecrucible.core.jobs import Line
    settings = {"min_similarity": 0.6, "intense_expressions": ["Hurt"], "intense_min_similarity": 0.63}
    plain = Line(key="K", character="A", text="x", emotion="Happy")
    own = Line(key="K", character="A", text="x", emotion="Happy", params={"check_min_similarity": 0.72})
    hurt = Line(key="K", character="A", text="x", emotion="Hurt", params={"check_intense_min_similarity": 0.65})
    assert limit(settings, plain, "min_similarity", 0.8) == 0.6
    assert limit(settings, own, "min_similarity", 0.8) == 0.72
    assert limit(settings, hurt, "min_similarity", 0.8) == 0.65
