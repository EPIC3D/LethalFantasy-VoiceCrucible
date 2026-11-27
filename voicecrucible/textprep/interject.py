"""Speakable spellings for short interjections. Engines read a bare "Mhm" as letters and produce noise
(heard: "muápp" for a Twin's "Mhm"); a spelled-out form is spoken as a sound. English only.
"""

from __future__ import annotations

import re

# whole word (any case) -> what the engine reads
SPOKEN = {
    "mhm": "Mm-hmm",
    "mhmm": "Mm-hmm",
    "mmhm": "Mm-hmm",
    "uhhuh": "Uh-huh",
    "hm": "Hmm",
    "hmph": "Hmmph",
    "tsk": "Tsk tsk",
    "ok": "okay",  # heard: "You ok?" read as "you oak"
}
_WORD = re.compile(r"\b(" + "|".join(sorted(SPOKEN, key=len, reverse=True)) + r")\b", re.IGNORECASE)


# stage directions written as a word ("Sigh... I didn't want to", "*gasp*"): acted as a sound, not read aloud.
# Only at the start of the line or between asterisks – "a big sigh" inside a sentence stays a word.
ACTED = {
    "sigh": "Haaah...",
    "sighs": "Haaah...",
    "gasp": "Hah!",
    "gasps": "Hah!",
}
_ACTED = re.compile(r"^(\W*)(" + "|".join(ACTED) + r")\b[.…,!]*|\*(" + "|".join(ACTED) + r")\*", re.IGNORECASE)


def fix(text: str) -> str:
    """Replace interjections the engines cannot read with spoken spellings, and act written-out sighs and gasps."""
    text = _ACTED.sub(lambda m: (m.group(1) or "") + ACTED[(m.group(2) or m.group(3)).lower()], text)
    return _WORD.sub(lambda m: SPOKEN[m.group(1).lower()], text)
