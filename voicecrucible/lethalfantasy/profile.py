"""The LethalFantasy profile folder: characters, expression meanings, emotion tables, lexicon, voices."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from voicecrucible.textprep.fallback import SoundFallbacks
from voicecrucible.textprep.pronounce import Lexicon


@dataclass
class Character:
    """One speaker of the game."""

    name: str
    folder: str
    prefix: str
    voices: dict[str, Path]
    bible: str
    persona: str
    chatterbox_adjust: tuple[float, float]


@dataclass
class Profile:
    """All game data the line builder needs."""

    folder: Path
    characters: dict[str, Character]
    expressions: dict[str, str]  # expression -> acting meaning
    emotions: dict
    lexicon: Lexicon
    sounds: SoundFallbacks = field(default_factory=lambda: SoundFallbacks([]))  # sound_fallbacks.json (optional)
    reference_text: str = ""  # reference_text.txt: what the "breeze" reference voices say, word for word
    reference_text_short: str = ""  # reference_text_short.txt: the start of it, said by voices/.../<name>.short.wav

    def voice(self, character: str, engine: str) -> Path | None:
        """Reference voice of a character for an engine (the acting reference for qwen_vc), if any."""
        return self.characters[character].voices.get(engine)


def add_new_characters(folder: Path, names: set[str]) -> list[str]:
    """Add speakers found in the game export but missing from characters.json, with editable defaults.

    The new entry has no reference voice yet, so its lines are skipped (with a message) until one is added.
    """
    path = folder / "characters.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    added = sorted(n for n in names if n not in data and not n.startswith("_"))
    folders_file = folder / "plugin_folders.json"
    plugin_folders = _json(folders_file) if folders_file.exists() else {}
    for name in added:
        data[name] = {"folder": plugin_folders.get(name, name.upper()), "prefix": f"{name.upper()}_DIALOGUE_",
                      "voices": {"chatterbox": f"voices/chatterbox/{name}.wav", "qwen_vc": f"voices/acting/{name}.wav",
                                 "breeze": f"voices/reference/{name}.wav"},
                      "bible": f"{name}, a character of LethalFantasy.", "persona": f"{name}.",
                      "chatterbox_adjust": [0.0, 0.0], "_added_automatically": "check folder, prefix, voices and bible"}
    if added:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    return added


def _json(path: Path) -> dict:
    """Read a JSON file without its '_comment'-style keys."""
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}


class ProfileMissing(FileNotFoundError):
    """The configured profile is not installed."""


def load(folder: Path) -> Profile:
    """Load a profile folder (see profiles/template for the format)."""
    if not (folder / "characters.json").exists():
        raise ProfileMissing(
            f"profile '{folder.name}' does not exist ({folder}). The bundled default is 'lethalfantasy'; create "
            f"your own with 'crucible profile new {folder.name}' (see docs/PROFILES.md) or check [render] profile.")
    chars = {}
    for name, c in _json(folder / "characters.json").items():
        chars[name] = Character(name=name, folder=c["folder"], prefix=c["prefix"],
                                voices={e: folder / p for e, p in c.get("voices", {}).items()},
                                bible=c.get("bible", ""), persona=c.get("persona", ""),
                                chatterbox_adjust=tuple(c.get("chatterbox_adjust", (0.0, 0.0))))
    expressions = {k: v.get("meaning", "") for k, v in _json(folder / "expressions.json").items() if isinstance(v, dict)}
    ref_text, ref_short = folder / "reference_text.txt", folder / "reference_text_short.txt"
    return Profile(folder, chars, expressions, _json(folder / "emotions.json"),
                   Lexicon.load(folder / "pronunciation.json"), SoundFallbacks.load(folder / "sound_fallbacks.json"),
                   ref_text.read_text(encoding="utf-8").strip() if ref_text.exists() else "",
                   ref_short.read_text(encoding="utf-8").strip() if ref_short.exists() else "")
