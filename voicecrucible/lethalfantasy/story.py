"""Memory Orb audiobook ("story mode"): the TWINS_TEASER pages, read by a narrator, with the Twins' coloured
lines in their own voices. No sound effects – the simplest version.

A page is split at `<color=...>` tags (colour -> speaker, from the profile's story.json); everything else is
the narrator (also the friend's quotes). Long parts are split at sentence ends so the engine stays reliable.
Each part is rendered as its own line (folder `_STORY_PARTS`, ignored by the plugin), then `join_pages`
puts each page together into `voices/<language>/STORY/<page key>.ogg`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voicecrucible.core import audio
from voicecrucible.core.jobs import Line
from voicecrucible.textprep import has_words, prepare
from voicecrucible.textprep.pronounce import Lexicon

PARTS_FOLDER = "_STORY_PARTS"
_COLOR = re.compile(r"<color=([^>]+)>(.*?)</color>", re.DOTALL | re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
MAX_PART_CHARS = 260
PAUSE_SAME, PAUSE_SWITCH = 0.25, 0.5  # seconds between parts of the same / a different speaker


@dataclass
class StoryConfig:
    """profiles/<profile>/story.json"""

    prefix: str
    folder: str
    narrator: str
    colors: dict[str, str]  # colour (lower case, as in the tag) -> speaker
    voices: dict[str, Path]  # speaker -> reference clip
    params: dict[str, dict]  # speaker -> engine settings


def load_config(profile_folder: Path) -> StoryConfig | None:
    """The profile's story settings, or None when the profile has no story.json."""
    path = profile_folder / "story.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return StoryConfig(prefix=d["prefix"], folder=d.get("folder", "STORY"), narrator=d["narrator"],
                       colors={k.lower(): v for k, v in d["colors"].items()},
                       voices={k: profile_folder / v for k, v in d["voices"].items()},
                       params=d.get("params", {}))


def split_page(text: str, cfg: StoryConfig) -> list[tuple[str, str]]:
    """[(speaker, raw text)] in reading order; unknown colours are read by the narrator."""
    parts: list[tuple[str, str]] = []
    pos = 0
    for m in _COLOR.finditer(text):
        if m.start() > pos:
            parts.append((cfg.narrator, text[pos:m.start()]))
        parts.append((cfg.colors.get(m.group(1).strip().lower(), cfg.narrator), m.group(2)))
        pos = m.end()
    parts.append((cfg.narrator, text[pos:]))
    return [(s, t) for s, t in parts if t.strip()]


def _chunks(text: str) -> list[str]:
    """Sentence groups of at most MAX_PART_CHARS characters."""
    out, current = [], ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + 1 + len(sentence) > MAX_PART_CHARS:
            out.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        out.append(current)
    return out


def build_lines(pages: dict[str, str], cfg: StoryConfig, lexicon: Lexicon,
                add_asset: Callable[[Path], str], language: str = "en", sounds=None) -> list[Line]:
    """Queue lines for every part of every page: key '<page>__p001', folder _STORY_PARTS."""
    ids = {spk: add_asset(path) for spk, path in cfg.voices.items() if path.exists()}
    missing = sorted(set(cfg.voices) - set(ids))
    if missing:
        raise FileNotFoundError(f"story reference voice(s) missing: {', '.join(missing)}")
    lines = []
    for page, text in sorted(pages.items(), key=lambda kv: _page_number(kv[0])):
        n = 0
        for speaker, raw in split_page(text, cfg):
            for chunk in _chunks(prepare(raw, lexicon, language=language)):
                if not has_words(chunk):
                    continue
                n += 1
                params = dict(cfg.params.get(speaker, {}))
                if language == "en" and sounds is not None and (say := sounds.find(chunk)) and not _words(chunk):
                    params["last_take_text"] = say  # a hum or a laugh: its last take says this
                lines.append(Line(key=f"{page}__p{n:03d}", character=PARTS_FOLDER, text=chunk, emotion=speaker,
                                  voice=ids[speaker], params=params))
    return lines


def _words(text: str) -> list[str]:
    from voicecrucible.checks.words import words
    return words(text)


def _page_number(key: str) -> int:
    m = re.search(r"(\d+)$", key)
    return int(m.group(1)) if m else 0


def join_pages(output_root: Path, language: str, cfg: StoryConfig, lines: list[Line],
               replace: bool = False, skipped: set[str] | None = None) -> tuple[list[str], dict]:
    """Join the rendered parts of every page into STORY/<page>.ogg; returns (joined pages, {page: missing parts}).

    A page file that already exists (perhaps edited by hand) is kept; with `replace` it is replaced and the old one
    is kept as <page>.bak.ogg.
    """
    parts_dir = output_root / "voices" / language / PARTS_FOLDER
    by_page: dict[str, list[Line]] = {}
    for ln in lines:
        if ln.key in (skipped or set()):  # left without a voice in the watcher (e.g. a hum the engine cannot do)
            continue
        by_page.setdefault(ln.key.rsplit("__p", 1)[0], []).append(ln)
    joined, missing = [], {}
    for page, page_lines in by_page.items():
        target = output_root / "voices" / language / cfg.folder / f"{page}.ogg"
        if target.exists() and not replace:
            continue
        files = [parts_dir / f"{ln.key}.ogg" for ln in page_lines]
        absent = [f.stem for f in files if not f.exists()]
        if absent:
            missing[page] = absent
            continue
        pieces, rate, previous = [], None, None
        for ln, f in zip(page_lines, files, strict=True):
            y, sr = audio.decode(f.read_bytes())
            rate = rate or sr
            if sr != rate:
                raise ValueError(f"{f.name}: sample rate {sr} differs from {rate}")
            if previous is not None:
                gap = PAUSE_SWITCH if ln.emotion != previous else PAUSE_SAME
                pieces.append(np.zeros(int(rate * gap), np.float32))
            pieces.append(y)
            previous = ln.emotion
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.replace(target.with_name(f"{page}.bak.ogg"))
        target.write_bytes(audio.encode(np.concatenate(pieces), rate, "ogg"))
        joined.append(page)
    return joined, missing
