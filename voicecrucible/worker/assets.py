"""Local cache of reference voices fetched from the coordinator, verified by SHA-256 before use."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{64}$")
_EXT = {".wav", ".flac", ".ogg"}


class AssetCache:
    """work/worker/assets/<sha256><ext>; `fetch(sha)` returns {"data": base64, "ext": ".wav"} from the coordinator."""

    def __init__(self, folder: Path, fetch: Callable[[str], dict]):
        self.folder = folder
        self._fetch = fetch

    def get(self, sha: str) -> Path:
        """Path of the asset, downloading and verifying it the first time."""
        if not _SHA.match(sha):
            raise ValueError(f"invalid asset id {sha!r}")
        for ext in _EXT:
            p = self.folder / f"{sha}{ext}"
            if p.exists():
                return p
        answer = self._fetch(sha)
        ext = answer.get("ext", "")
        if ext not in _EXT:
            raise ValueError(f"asset {sha[:12]} has an unexpected type {ext!r}")
        data = base64.b64decode(answer.get("data", ""), validate=True)
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError(f"asset {sha[:12]} failed the checksum – not used")
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / f"{sha}{ext}"
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        return target
