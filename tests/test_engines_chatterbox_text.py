"""Retakes of one-word exclamations stretch the vowel instead of repeating the same failing input."""

from voicecrucible.engines.chatterbox import longer_sound
from voicecrucible.checks.words import compare


def test_one_word_retakes_stretch_the_first_vowel():
    assert longer_sound("Hey!", 1) == "Hey!"
    assert longer_sound("Hey!", 2) == "Heey!"
    assert longer_sound("Stomp!", 3) == "Stooomp!"
    assert longer_sound("Two words", 2) == "Two words"
    assert compare("Hey!", "Heeey!", {})["ratio"] == 1.0
