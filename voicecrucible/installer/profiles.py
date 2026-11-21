"""Profile packs: install a profile zip into profiles/<name>/, update it without losing your changes, list them.

A pack is a zip with one top folder holding profile.json (name, version, ...), characters.json, emotions.json,
expressions.json, pronunciation.json, director_brief.md and voices/. Installing over an existing profile first
copies the old one to profiles/<name>.backup-<date>/, and keeps reference voices the new pack does not bring.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from voicecrucible.core import log
from voicecrucible.installer import layout

_log = log.get("profile")
REQUIRED = ("profile.json", "characters.json", "emotions.json", "expressions.json", "pronunciation.json")


class ProfileError(RuntimeError):
    """The pack is not a valid profile; nothing was changed."""


def profiles_dir(root: Path = layout.ROOT) -> Path:
    """Where profiles live."""
    return root / "profiles"


def _manifest(zf: zipfile.ZipFile) -> tuple[str, dict]:
    """Top folder and profile.json of a pack, after checking that every required file is there."""
    tops = {n.split("/")[0] for n in zf.namelist() if n.strip("/")}
    if len(tops) != 1:
        raise ProfileError("a profile pack must contain exactly one folder")
    top = tops.pop()
    missing = [f for f in REQUIRED if f"{top}/{f}" not in zf.namelist()]
    if missing:
        raise ProfileError(f"not a profile pack – missing: {', '.join(missing)}")
    meta = json.loads(zf.read(f"{top}/profile.json"))
    name = str(meta.get("name", ""))
    if not name or not name.replace("-", "").replace("_", "").isalnum() or name == "template":
        raise ProfileError(f"invalid profile name {name!r}")
    return top, meta


def install(pack: Path, root: Path = layout.ROOT) -> tuple[dict, Path | None]:
    """Install or update a profile pack; returns its profile.json and the backup folder (if one was made)."""
    with zipfile.ZipFile(pack) as zf:
        top, meta = _manifest(zf)
        target = profiles_dir(root) / meta["name"]
        backup = None
        if target.exists():
            backup = target.with_name(f"{target.name}.backup-{datetime.now():%Y%m%d-%H%M%S}")
            shutil.copytree(target, backup)
        for member in zf.infolist():
            rel = member.filename[len(top) + 1:]
            if not rel or member.is_dir():
                continue
            out = (target / rel).resolve()
            if target.resolve() not in out.parents:
                raise ProfileError(f"unsafe path in pack: {member.filename}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(member))
    return meta, backup


def new_profile(name: str, root: Path = layout.ROOT) -> Path:
    """Create profiles/<name> as a copy of the template (without its example character)."""
    if not name.replace("-", "").replace("_", "").isalnum() or name == "template":
        raise ProfileError(f"invalid profile name {name!r} (letters, digits, - and _)")
    target = profiles_dir(root) / name
    if target.exists():
        raise ProfileError(f"profile '{name}' already exists: {target}")
    shutil.copytree(profiles_dir(root) / "template", target, ignore=shutil.ignore_patterns(".gitignore"))
    meta = json.loads((target / "profile.json").read_text(encoding="utf-8"))
    meta.update(name=name, title=name, version="1.0.0", description="Created from the template.")
    (target / "profile.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    chars = json.loads((target / "characters.json").read_text(encoding="utf-8"))
    chars = {k: v for k, v in chars.items() if k.startswith("_")}  # speakers are added from the game export
    (target / "characters.json").write_text(json.dumps(chars, indent=2) + "\n", encoding="utf-8")
    for engine in ("chatterbox", "acting"):
        (target / "voices" / engine).mkdir(parents=True, exist_ok=True)
    return target


def new_command(name: str | None) -> int:
    """`crucible profile new <name>`."""
    if not name:
        _log.error("give the profile a name: crucible profile new lethalfantasy")
        return 1
    try:
        target = new_profile(name)
    except (ProfileError, OSError) as e:
        _log.error("%s", e)
        return 1
    _log.info("profile created: %s", target)
    _log.info("next: 'crucible render --lines <export> --dry-run' adds the game's speakers to characters.json; "
              "then put one reference clip per speaker into %s (file names are shown)", target / "voices" / "chatterbox")
    return 0


def installed(root: Path = layout.ROOT) -> list[dict]:
    """profile.json of every installed profile (backups excluded)."""
    out = []
    for folder in sorted(profiles_dir(root).glob("*/profile.json")):
        if ".backup-" not in folder.parent.name:
            meta = json.loads(folder.read_text(encoding="utf-8"))
            meta["folder"] = folder.parent.name
            out.append(meta)
    return out


def install_command(pack: Path | None) -> int:
    """`crucible profile install <zip>`."""
    if pack is None or not pack.exists():
        _log.error("give the profile pack zip: crucible profile install <file.zip>")
        return 1
    try:
        meta, backup = install(pack)
    except (ProfileError, zipfile.BadZipFile, ValueError, OSError) as e:
        _log.error("profile not installed: %s", e)
        return 1
    _log.info("profile '%s' %s installed (%s)", meta["name"], meta.get("version", "?"), meta.get("title", ""))
    if backup is not None:
        _log.info("the previous version (with your changes) is kept in %s", backup)
    _log.info("use it with [render] profile = \"%s\" (the default is \"lethalfantasy\")", meta["name"])
    return 0


def list_command(active: str) -> int:
    """`crucible profile list`."""
    for meta in installed():
        mark = "*" if meta["folder"] == active else " "
        print(f"{mark} {meta['folder']:<20} {meta.get('version', '?'):<8} {meta.get('title', '')}")
    print("(* = active, set with [render] profile)")
    return 0
