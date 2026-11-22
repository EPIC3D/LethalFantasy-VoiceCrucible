"""Store rendered audio in the voice pack layout the plugin expects: voices/<language>/<CHARACTER>/<KEY>.<ext>.

The path is built only from the coordinator's own queue data, never from what a worker sends, and every
part is checked against a strict pattern – a worker cannot write outside the output folder.
"""

from __future__ import annotations

import re
from pathlib import Path

from voicecrucible.core.jobs import Line

_SAFE = re.compile(r"^[A-Za-z0-9_\-]{1,200}$")
AUDIO_EXTENSIONS = {"wav", "ogg"}
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class UnsafeName(ValueError):
    """A key, character, language or extension that is not allowed in a file path."""


def output_path(root: Path, language: str, line: Line, ext: str) -> Path:
    """Target file of a line inside the output folder."""
    for part in (language, line.character, line.file_stem):
        if not _SAFE.match(part):
            raise UnsafeName(f"not allowed in a file name: {part!r}")
    if ext not in AUDIO_EXTENSIONS:
        raise UnsafeName(f"audio type not allowed: {ext!r}")
    return root / "voices" / language / line.character / f"{line.file_stem}.{ext}"


def save_candidate(folder: Path, line: Line, ext: str, data: bytes) -> Path:
    """Store a failed take (named by queue row and attempt only – no worker-supplied names)."""
    if ext not in AUDIO_EXTENSIONS:
        raise UnsafeName(f"audio type not allowed: {ext!r}")
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("audio file too large")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{int(line.uid)}_a{int(line.attempt)}.{ext}"
    target.write_bytes(data)
    return target


def save(root: Path, language: str, line: Line, ext: str, data: bytes) -> Path:
    """Write one audio file atomically (a half-written file is never left behind). A file that is already there
    (rendered again with --all, perhaps edited by hand) is kept as <name>.bak.<ext>."""
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("audio file too large")
    target = output_path(root, language, line, ext)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(data)
    if target.exists():
        target.replace(target.with_name(f"{target.stem}.bak.{ext}"))
    tmp.replace(target)
    return target
