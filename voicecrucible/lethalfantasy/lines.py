"""Read the line export the LethalFantasy TTS plugin writes from the player's own game.

Input folder (plugin setting [Developer] ExportLines = true):
- english_lines.jsonl   {"key", "text"}  – every translation key with its English text
- dialogue_events.jsonl {"asset", "event", "line", "key", "character", "type", "expression", ...}
Lines without an event (e.g. some interaction groups) get their speaker from the key prefix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from voicecrucible.lethalfantasy.profile import Profile


@dataclass
class SourceLine:
    """A line as the game has it: key, speaker, type, expression, raw text (with tags and placeholders)."""

    key: str
    character: str
    type: str
    expression: str
    text: str
    scene: str = ""  # the dialogue asset (scene) it belongs to – used to give a director context
    order: tuple = ()


def _jsonl(path: Path) -> list[dict]:
    """Read a JSON-lines file, skipping empty lines."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def speakers(folder: Path) -> set[str]:
    """Every speaking character named in the export's dialogue events."""
    events = folder / "dialogue_events.jsonl"
    return {e["character"] for e in _jsonl(events) if e.get("character")} if events.exists() else set()


def read_export(folder: Path, profile: Profile, texts_file: Path | None = None) -> list[SourceLine]:
    """All dialogue lines of the known characters, in game order, one entry per (key, speaker).

    `texts_file` replaces the English texts with another language ({"key", "text"} lines, e.g. from Weblate);
    speakers and expressions still come from the export's dialogue events.
    """
    texts = {r["key"]: r["text"] for r in _jsonl(texts_file or folder / "english_lines.jsonl")}
    out: list[SourceLine] = []
    seen: set[tuple[str, str]] = set()
    events = folder / "dialogue_events.jsonl"
    for e in (_jsonl(events) if events.exists() else []):
        key, ch = e.get("key", ""), e.get("character", "")
        if ch in profile.characters and key in texts and (key, ch) not in seen:
            seen.add((key, ch))
            out.append(SourceLine(key, ch, e.get("type") or "Normal", e.get("expression") or "Neutral", texts[key],
                                  e.get("asset", ""), (e.get("asset", ""), e.get("event", 0), e.get("line", 0))))
    with_event = {k for k, _ in seen}
    for key, text in texts.items():  # lines the events do not list: speaker from the key prefix
        if key in with_event:
            continue
        for ch in profile.characters.values():
            if key.startswith(ch.prefix):
                out.append(SourceLine(key, ch.name, "Normal", "Neutral", text, key.rsplit("_", 1)[0], (key,)))
                break
    return out
