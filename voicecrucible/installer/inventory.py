"""INSTALLED.txt: what is installed, which version, how big, and exactly where – always current."""

from __future__ import annotations

import importlib.metadata
from datetime import datetime
from pathlib import Path

from voicecrucible import __version__
from voicecrucible.installer import layout


def folder_size(path: Path) -> int:
    """Total size of the files below `path` in bytes (0 if missing)."""
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def _gb(n: int) -> str:
    return f"{n / 1024 ** 3:.2f} GB" if n >= 100 * 1024 ** 2 else f"{n / 1024 ** 2:.1f} MB"


def packages() -> list[tuple[str, str, int, str]]:
    """Installed Python packages of this environment: name, version, size, folder."""
    out = []
    for dist in importlib.metadata.distributions():
        files = dist.files or []
        size = sum((f.size or 0) for f in files)
        location = str(Path(dist.locate_file("")).resolve())
        out.append((dist.metadata["Name"] or "?", dist.version, size, location))
    return sorted(out, key=lambda p: p[0].lower())


def write(root: Path = layout.ROOT, components: list[str] | None = None) -> Path:
    """Rewrite INSTALLED.txt in the install folder and return its path."""
    lines = [f"Voice Crucible {__version__} – installed files (updated {datetime.now():%Y-%m-%d %H:%M})",
             f"Install folder: {root}", "Uninstall: delete this folder. Nothing was installed anywhere else.", ""]
    if components:
        lines += ["Components: " + ", ".join(components), ""]
    lines.append("FOLDERS")
    for title, path in layout.folders(root).items():
        if path.exists():
            lines.append(f"  {_gb(folder_size(path)):>10}  {title}\n              {path}")
    lines += ["", "PYTHON PACKAGES (name, version, size, folder)"]
    for name, version, size, location in packages():
        lines.append(f"  {name} {version}  {_gb(size)}  {location}")
    target = root / "INSTALLED.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")  # BOM: Windows tools detect UTF-8
    return target
