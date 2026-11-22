"""Remembers which package list (uv.lock) the installed environment matches, to tell when setup must run again.

setup and the post-update resync write runtime/setup_state.json; the watcher and the worker compare it with the
current uv.lock (e.g. after unzipping a new version by hand).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from voicecrucible import __version__
from voicecrucible.installer import layout


def _lock_hash(root: Path) -> str:
    """Fingerprint of the third-party packages in uv.lock. Voice Crucible's own entry is left out: its version
    changes with every release although no package has to be installed for that."""
    try:
        text = (root / "uv.lock").read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError:
        return ""
    sep = "\n[[package]]\n"
    kept = [b for b in text.split(sep) if not b.startswith('name = "voicecrucible"\n')]
    return hashlib.sha256(sep.join(kept).encode("utf-8")).hexdigest()


def _state_file(root: Path) -> Path:
    return layout.runtime(root) / "setup_state.json"


def record(root: Path = layout.ROOT) -> None:
    """Note that the environment now matches this version's uv.lock."""
    try:
        f = _state_file(root)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"packages_sha256": _lock_hash(root), "version": __version__}, indent=1), encoding="utf-8")
    except OSError:
        pass


def needed(root: Path = layout.ROOT) -> str:
    """Why setup should run again ('' when the environment matches, or when this is not an installed copy)."""
    lock = _lock_hash(root)
    if not lock or not (layout.runtime(root) / "venv").exists():
        return ""
    try:
        state = json.loads(_state_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "setup has not been run with this version yet"
    if state.get("packages_sha256") != lock:
        return f"this version ({__version__}) needs packages that are not installed yet (last setup: {state.get('version', '?')})"
    return ""
