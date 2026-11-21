"""Remove what engines would read aloud or stumble over: TextMeshPro tags, symbols, odd whitespace."""

from __future__ import annotations

import re

_TAGS = re.compile(r"<[^>]+>")
_SYMBOLS = re.compile(r"[~*#_=+\[\]{}|\\^`]")
_TILDE_PAUSE = re.compile(r"~+(?=\s+\w)")


def strip_tags(text: str) -> str:
    """Remove rich-text tags like <i>, <color=red>, </b>."""
    return _TAGS.sub("", text)


def tidy(text: str) -> str:
    """Keep a tilde's pause as a comma ('Hey~ I' -> 'Hey, I'), drop symbols, normalise dots and spaces."""
    t = _TILDE_PAUSE.sub(",", text)
    t = _SYMBOLS.sub("", t)
    t = t.replace("…", "...")
    return re.sub(r"\s+", " ", t).strip()
