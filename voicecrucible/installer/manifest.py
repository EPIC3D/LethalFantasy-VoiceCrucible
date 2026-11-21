"""The download list (downloads.toml): components, sources, licenses, sizes – shown before installing."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST = Path(__file__).parents[2] / "downloads.toml"


@dataclass
class Component:
    """One installable part."""

    key: str
    title: str
    license: str
    source: str
    download_gb: float
    disk_gb: float
    extras: list[str] = field(default_factory=list)
    required: bool = False
    required_for: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # component-specific data (e.g. Seed-VC commit and checksum)


def load(path: Path = MANIFEST) -> dict[str, Component]:
    """All components of the download list, in file order."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))["components"]
    known = {"title", "license", "source", "download_gb", "disk_gb", "extras", "required", "required_for"}
    return {k: Component(key=k, title=v["title"], license=v["license"], source=v["source"],
                         download_gb=float(v["download_gb"]), disk_gb=float(v["disk_gb"]),
                         extras=list(v.get("extras", [])), required=bool(v.get("required", False)),
                         required_for=list(v.get("required_for", [])),
                         extra={x: y for x, y in v.items() if x not in known})
            for k, v in data.items()}


def resolve(components: dict[str, Component], wanted: set[str]) -> list[Component]:
    """Wanted components plus everything they need (required ones and e.g. PyTorch), in file order."""
    chosen = set(wanted) | {k for k, c in components.items() if c.required}
    chosen |= {k for k, c in components.items() if set(c.required_for) & chosen}
    unknown = chosen - set(components)
    if unknown:
        raise ValueError(f"unknown component(s): {', '.join(sorted(unknown))}")
    return [c for k, c in components.items() if k in chosen]


def table(selected: list[Component]) -> str:
    """Readable list with sizes, sources and licenses, plus totals."""
    lines = []
    for c in selected:
        lines += [f"* {c.title}", f"    download ~{c.download_gb:.1f} GB, on disk ~{c.disk_gb:.1f} GB",
                  f"    from:    {c.source}", f"    license: {c.license}"]
    lines.append(f"TOTAL: download ~{sum(c.download_gb for c in selected):.1f} GB, "
                 f"on disk ~{sum(c.disk_gb for c in selected):.1f} GB")
    return "\n".join(lines)
