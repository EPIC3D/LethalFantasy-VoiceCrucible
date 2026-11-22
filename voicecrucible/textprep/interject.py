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
}
_WORD = re.compile(r"\b(" + "|".join(sorted(SPOKEN, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def fix(text: str) -> str:
    """Replace interjections the engines cannot read with spoken spellings."""
    return _WORD.sub(lambda m: SPOKEN[m.group(1).lower()], text)
