"""Reference voice files the workers need, stored by their SHA-256 (content address).

Only files added here on purpose can be fetched, and only by exact hash – a worker cannot read anything else.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

ALLOWED = {".wav", ".flac", ".ogg"}
_SHA = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    """SHA-256 of a file as lowercase hex."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class AssetStore:
    """Folder of content-addressed files: <sha256><ext>."""

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def add(self, path: Path) -> str:
        """Copy a reference file into the store; returns its ID (SHA-256)."""
        if path.suffix.lower() not in ALLOWED:
            raise ValueError(f"reference voice must be one of {sorted(ALLOWED)}: {path}")
        sha = sha256_file(path)
        target = self.folder / f"{sha}{path.suffix.lower()}"
        if not target.exists():
            shutil.copyfile(path, target)
        return sha

    def get(self, sha: str) -> Path | None:
        """The stored file for an ID, or None (also for anything that is not a plain SHA-256)."""
        if not _SHA.match(sha):
            return None
        for ext in ALLOWED:
            p = self.folder / f"{sha}{ext}"
            if p.exists():
                return p
        return None
