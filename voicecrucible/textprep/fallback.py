"""Fallback words for lines without words (a hum, a laugh, a sigh), from the profile's sound_fallbacks.json.

When the engine cannot make the sound, the last take of such a line says a short phrase with the same meaning
("Mm-hmm" -> "Yes.", "Hehe..." -> "That is funny!"). Rules are tried in order; the first that matches wins:

    {"sound": "<regex every word of the line must match>", "ends_with": "?", "expressions": ["Happy"], "say": "..."}

`ends_with` and `expressions` are optional. The subtitle in the game never changes – only the spoken take.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Rule:
    """One fallback rule."""

    sound: re.Pattern
    say: str
    ends_with: str = ""
    expressions: tuple[str, ...] = ()


class SoundFallbacks:
    """The rules of one profile (none when the file is missing)."""

    def __init__(self, rules: list[Rule]):
        self.rules = rules

    @classmethod
    def load(cls, path: Path) -> SoundFallbacks:
        """Read sound_fallbacks.json; a missing file means no fallbacks."""
        if not path.exists():
            return cls([])
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Rule(re.compile(r["sound"], re.IGNORECASE), str(r["say"]), str(r.get("ends_with", "")),
                         tuple(r.get("expressions", ()))) for r in data.get("rules", [])])

    def find(self, text: str, expression: str = "") -> str:
        """The phrase for this sound and expression ('' when no rule matches)."""
        tokens = re.findall(r"[a-z]+(?:-[a-z]+)*", text.lower())
        end = text.strip().strip('"\'~ ')[-1:] if text.strip().strip('"\'~ ') else ""
        for rule in self.rules:
            if (tokens and all(rule.sound.fullmatch(t) for t in tokens)
                    and (not rule.ends_with or end == rule.ends_with)
                    and (not rule.expressions or expression in rule.expressions)):
                return rule.say
        return ""
