"""Tests for the text preparation (rules from the old pipeline, user-approved). Uses the invented test profile."""

from pathlib import Path

import pytest

from voicecrucible.textprep import has_words, prepare, pronounce

LEX = pronounce.Lexicon.load(Path(__file__).parent / "data" / "profile" / "pronunciation.json")


@pytest.mark.parametrize("raw, spoken", [
    ("M-mommy?", "Mom... mommy?"),
    ("S-say that again?", "Say... say that again?"),
    ("H.. Hey! Why you do that for?!", "Hey... Hey! Why you do that for?!"),
    ("I just… I-I can't handle this right now", "I just... I... I can't handle this right now"),
    ("A-anyway! I'm glad", "An... anyway! I'm glad"),
    ("Hehehe, Ornella~ I love it when you are so naughty~", "Hehehe, Ornehlla, I love it when you are so naughty"),
    ("<i>Nell</i>, you would blow the whole house down", "Nehll, you would blow the whole house down"),
    ("I'm Mira by the way", "I'm Meerah by the way"),
])
def test_prepare(raw, spoken):
    assert prepare(raw, LEX) == spoken


def test_name_variant_and_whole_words():
    assert prepare("Ornella", LEX, name_variant=1) == "Orrnehlla"
    assert prepare("Nellie", LEX) == "Nellie"  # only whole words


def test_has_words():
    assert not has_words(prepare("…~", LEX))
    assert has_words("Hm")


def test_respellings_map_back_to_names():
    assert LEX.respellings()["orrnehlla"] == "orn"
