"""Turn a game line into the text a TTS engine speaks. Subtitles in the game stay unchanged.

Steps, each in its own module: rich-text tags out (clean), natural stutters (stutter), speakable interjections
(interject: 'Mhm' -> 'Mm-hmm'), name respellings (pronounce), then symbols out and whitespace tidied (clean).
"""

from __future__ import annotations

from voicecrucible.textprep import clean, interject, pronounce, stutter


def prepare(text: str, lexicon: pronounce.Lexicon | None = None, name_variant: int = 0, language: str = "en") -> str:
    """Speakable text for one line (the interjection spellings are English, used only for English packs)."""
    t = clean.strip_tags(text)
    t = stutter.fix(t)
    if language == "en":
        t = interject.fix(t)
    if lexicon is not None:
        t = lexicon.apply(t, name_variant)
    return clean.tidy(t)


def has_words(text: str) -> bool:
    """True when the prepared text has anything to speak (lines like '...' or '~' have not)."""
    return any(ch.isalpha() for ch in text)
