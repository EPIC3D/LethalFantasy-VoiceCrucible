"""Name respellings, so engines pronounce names right ('Ornella' -> 'Ornehlla'). Loaded from a JSON lexicon.

Lexicon format: {"Name": ["Respelling", "Alternative", ...], "_comment": "..."}; keys starting with '_' are
ignored. Respellings are one word without hyphens (hyphens made engines spell the name or pause).
"""

from __future__ import annotations

import json
import re
from pathlib import Path


class Lexicon:
    """Whole-word name replacements, longest names first."""

    def __init__(self, entries: dict[str, list[str]]):
        self._entries = sorted(((k, v) for k, v in entries.items() if not k.startswith("_") and v),
                               key=lambda kv: -len(kv[0]))
        self._patterns = {name: re.compile(rf"\b{re.escape(name)}\b") for name, _ in self._entries}

    @classmethod
    def load(cls, path: Path) -> Lexicon:
        """Read a lexicon JSON file."""
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def apply(self, text: str, variant: int = 0) -> str:
        """Replace every known name; `variant` picks an alternative respelling (clamped to what exists)."""
        for name, spellings in self._entries:
            text = self._patterns[name].sub(spellings[min(variant, len(spellings) - 1)], text)
        return text

    def names(self) -> list[str]:
        """The written names (e.g. as a hint for speech recognition)."""
        return [name for name, _ in self._entries]

    def respellings(self) -> dict[str, str]:
        """Lower-case respelling -> lower-case name prefix, for checking that names were spoken."""
        return {s.lower(): name.lower()[:3] for name, spellings in self._entries for s in spellings}
