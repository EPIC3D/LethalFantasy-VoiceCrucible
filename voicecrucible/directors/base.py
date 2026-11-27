"""Director interface, scenes handed to a director, and reading/writing directions files."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

FIELDS = ("scene", "intent", "subtext", "delivery", "avoid", "energy", "pace")  # energy 1-5, pace slow|normal|fast


@dataclass
class SceneLine:
    """One line of a scene as a director sees it. Unvoiced lines (the player's) are context only."""

    key: str
    speaker: str
    text: str
    expression: str
    voiced: bool
    alt: int = -1  # which random alternative of the scene it belongs to (-1 = unknown); alternatives are not one talk


class Director(ABC):
    """Creates acting directions for the voiced lines of a scene."""

    @abstractmethod
    def direct(self, scene: str, lines: list[SceneLine]) -> dict[str, dict]:
        """Directions for the voiced lines of one scene: {key: {scene, intent, subtext, delivery, avoid}}."""


def clean(raw: dict) -> dict[str, dict]:
    """Keep only well-formed directions: string fields, known names, no extra data."""
    out = {}
    for key, d in raw.items():
        if isinstance(key, str) and isinstance(d, dict):
            out[key] = {f: str(d.get(f, ""))[:400] for f in FIELDS}
    return out


def load(path: Path) -> dict[str, dict]:
    """Read a directions file, or every *.json in a folder (later files win)."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    merged: dict[str, dict] = {}
    for f in files:
        merged.update(clean(json.loads(f.read_text(encoding="utf-8"))))
    return merged


def save(path: Path, directions: dict[str, dict]) -> None:
    """Write a directions file atomically, sorted by key so diffs stay readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(directions.items())), indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
