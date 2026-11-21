"""Written stutters ('M-mommy', 'H.. Hey', 'I-I') -> a stuttered onset a person would actually say.

A lone letter ('M-') is read as 'em' and a bare 'Mo'/'Sa' sounds like 'mooo'/'sahh', so the fragment
becomes the whole short word ('Say... say') or the first syllable with its closing consonant ('Mom... mommy').
"""

from __future__ import annotations

import re

# a 1-2 letter fragment, then - or .. or …, then a word starting with the same letters
_STUTTER = re.compile(r"\b([A-Za-z]{1,2})(?:-|\.{2,}|…)\s*(?=(\1)([A-Za-z']*))", re.IGNORECASE)
_SYLLABLE = re.compile(r"([^aeiouAEIOU]*[aeiouAEIOU]+)([^aeiouAEIOU]?)(.?)")


def onset(word: str) -> str:
    """Stutter fragment for a word: short words whole, longer ones up to the first syllable's closing consonant."""
    if len(word) <= 4:
        return word
    m = _SYLLABLE.match(word)
    if not m:
        return word
    head, cons, nxt = m.groups()
    if cons and (cons.lower() == "c" or nxt.lower() == "h"):  # don't split ch / sh / th / ck
        cons = ""
    return head + cons


def fix(text: str) -> str:
    """Rewrite every written stutter in `text`."""
    def rep(m: re.Match) -> str:
        frag = m.group(1)
        if frag.upper() == "I":
            return frag + "... "
        return onset(frag[0] + (m.group(2) + m.group(3))[1:]) + "... "
    return _STUTTER.sub(rep, text)
