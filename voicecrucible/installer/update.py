"""`crucible update`: manual, user-started update from the GitHub releases, verified before anything changes.

Steps: ask GitHub for the latest release -> show version, notes and size -> ask -> download the release zip
and its signature -> verify the Ed25519 signature with the public key below (only the maintainer has the
private key) -> move the current program files to previous\\ -> unpack the new ones.
Never touched: runtime\\ (installed parts), work\\ (pairing, queue), output\\, logs\\, voicecrucible.toml,
profiles\\ (your own and installed profiles; only the bundled template\\ and lethalfantasy\\ are
updated). `crucible update --rollback`
restores previous\\. No background checks exist.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path

from voicecrucible import __version__
from voicecrucible.core import log
from voicecrucible.installer import layout

_log = log.get("update")
REPO = "EPIC3D/LethalFantasy-VoiceCrucible"
# Ed25519 public key of the maintainer (base64). Only zips signed with the matching private key are installed.
PUBLIC_KEY = "O2ZJW3tNabOy1DJAsr9oxIJUEzE07tpgk5MwrxN9x98="
KEEP = {"runtime", "work", "output", "logs", "previous", "profiles", "voicecrucible.toml", "INSTALLED.txt", "uv.exe",
        ".git", ".venv"}  # profiles\ = your own and installed profiles – except the bundled ones below
SHIPPED_PROFILES = ("profiles/template/", "profiles/lethalfantasy/")  # replaced by every program update


class UpdateError(RuntimeError):
    """The update was refused or failed; nothing was changed."""


def verify(data: bytes, signature_b64: str, public_key_b64: str = PUBLIC_KEY) -> None:
    """Raise UpdateError unless `data` carries a valid signature of the maintainer."""
    if not public_key_b64:
        raise UpdateError("this version has no update key – download new versions manually from GitHub")
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(base64.b64decode(signature_b64.strip()), data)
    except (InvalidSignature, ValueError) as e:
        raise UpdateError("the download's signature is not valid – NOT installed") from e


def _version_tuple(v: str) -> tuple:
    """'0.1.0b2' -> comparable tuple (pre-releases sort before the final version)."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?(?:\.dev(\d+))?$", v)
    if not m:
        raise UpdateError(f"unknown version format: {v!r}")
    major, minor, patch, pre, pre_n, dev = m.groups()
    stage = {"a": 0, "b": 1, "rc": 2, None: 3}[pre]
    return int(major), int(minor), int(patch), stage, int(pre_n or 0), -1 if dev is None else int(dev)


def tag_to_version(tag: str) -> str:
    """GitHub tag -> program version: 'v0.1.0-beta.2' -> '0.1.0b2', 'v0.2.0' -> '0.2.0'."""
    v = tag.lstrip("v")
    for word, short in (("alpha", "a"), ("beta", "b"), ("rc", "rc")):
        v = re.sub(rf"-{word}\.?(\d+)", rf"{short}\1", v)
    return v


def is_newer(version: str, current: str = __version__) -> bool:
    """True when `version` is newer than `current` (unknown formats count as newer, the zip check decides)."""
    try:
        return _version_tuple(version) > _version_tuple(current)
    except UpdateError:
        return True


def zip_prefix(z: zipfile.ZipFile) -> str:
    """'' when the program files are at the zip's top level, 'VoiceCrucible/' when they are in one folder."""
    if "voicecrucible/__init__.py" in z.namelist():
        return ""
    tops = {n.split("/")[0] for n in z.namelist() if "/" in n}
    if len(tops) == 1 and f"{next(iter(tops))}/voicecrucible/__init__.py" in z.namelist():
        return next(iter(tops)) + "/"
    raise UpdateError("the download is not a Voice Crucible release")


def zip_version(data: bytes) -> str:
    """Version written inside the (signed) zip – the tag name of a release is not trusted."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read(zip_prefix(z) + "voicecrucible/__init__.py").decode("utf-8")
    m = re.search(r'__version__ = "([^"]+)"', text)
    if not m:
        raise UpdateError("the download has no version number")
    return m.group(1)


def check_newer(data: bytes, current: str = __version__) -> str:
    """Refuse downgrades: an old, validly signed release with known bugs must not be installed as an 'update'."""
    new = zip_version(data)
    if _version_tuple(new) <= _version_tuple(current):
        raise UpdateError(f"the download is version {new}, not newer than the installed {current} – NOT installed")
    return new


def _get(url: str) -> bytes:
    """HTTPS GET (GitHub only)."""
    if not url.startswith("https://"):
        raise UpdateError(f"refusing non-HTTPS download: {url}")
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream, application/json",
                                               "User-Agent": "VoiceCrucible-updater"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def latest() -> dict:
    """Latest release: version, notes, zip and signature URLs, size."""
    rel = json.loads(_get(f"https://api.github.com/repos/{REPO}/releases/latest"))
    assets = {a["name"]: a for a in rel.get("assets", [])}
    zips = [n for n in assets if n.endswith(".zip")]
    if not zips or zips[0] + ".sig" not in assets:
        raise UpdateError("the latest release has no signed program zip")
    z = assets[zips[0]]
    return {"version": tag_to_version(rel["tag_name"]), "notes": rel.get("body", ""), "zip": z["browser_download_url"],
            "sig": assets[zips[0] + ".sig"]["browser_download_url"], "size": z["size"]}


def _program_items(root: Path) -> list[Path]:
    """Top-level items that belong to the program (everything except user data and installed parts)."""
    return [p for p in root.iterdir() if p.name not in KEEP]


def backup_changed_bundled_profiles(z: zipfile.ZipFile, prefix: str, root: Path) -> list[Path]:
    """Copy a bundled profile that differs from the new release (edited by the user, or with files added) to
    profiles\\<name>.backup-<date>\\ before the update replaces it. Returns the backup folders."""
    from datetime import datetime
    made = []
    for shipped in SHIPPED_PROFILES:
        current = root / shipped
        if not current.exists():
            continue
        new = {n[len(prefix + shipped):]: n for n in z.namelist()
               if n.startswith(prefix + shipped) and not n.endswith("/")}
        have = {p.relative_to(current).as_posix(): p for p in current.rglob("*") if p.is_file()}
        changed = set(have) != set(new) or any(have[f].read_bytes() != z.read(new[f]) for f in have)
        if changed:
            target = current.with_name(f"{current.name}.backup-{datetime.now():%Y%m%d-%H%M%S}")
            shutil.copytree(current, target)
            made.append(target)
    return made


def install(data: bytes, root: Path = layout.ROOT) -> None:
    """Replace the program files with the (already verified) release zip; the old files go to previous\\."""
    previous = root / "previous"
    if previous.exists():
        shutil.rmtree(previous)
    previous.mkdir()
    for item in _program_items(root):
        shutil.move(str(item), previous / item.name)
    staging = root / "previous" / "_new.zip"
    staging.write_bytes(data)
    with zipfile.ZipFile(staging) as z:
        prefix = zip_prefix(z)
        for folder in backup_changed_bundled_profiles(z, prefix, root):
            _log.info("your changes to a bundled profile were saved to %s", folder)
        for member in z.infolist():
            name = member.filename[len(prefix):] if member.filename.startswith(prefix) else ""
            if not name:
                continue
            out = (root / name).resolve()
            shipped = name.startswith(SHIPPED_PROFILES)  # the bundled profiles are part of the program
            if root.resolve() not in out.parents or (name.split("/")[0] in KEEP and not shipped):
                continue  # never write outside the folder or over user data
            if member.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(member))
    staging.unlink()


def rollback(root: Path = layout.ROOT) -> None:
    """Put the previous program files back."""
    previous = root / "previous"
    if not previous.exists():
        raise UpdateError("there is no previous version to go back to")
    for item in _program_items(root):
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in previous.iterdir():
        if not item.name.startswith("_"):
            shutil.move(str(item), root / item.name)
    shutil.rmtree(previous)


def download_and_install(rel: dict) -> str:
    """Download, verify (signature + newer version) and install a release; returns the installed version.

    Shared by the manual update and a worker's self-update after a coordinator's update request.
    """
    data = _get(rel["zip"])
    verify(data, _get(rel["sig"]).decode("ascii"))
    version = check_newer(data)
    install(data)
    resync_components()
    return version


# installed component -> the module that shows it is installed
_COMPONENT_MODULES = {"gpu": "torch", "checks": "whisper", "chatterbox": "chatterbox", "qwen": "qwen_tts"}


def installed_extras() -> list[str]:
    """Components (uv extras) installed in this environment."""
    import importlib.util
    return [extra for extra, module in _COMPONENT_MODULES.items() if importlib.util.find_spec(module) is not None]


def resync_components(root: Path = layout.ROOT) -> None:
    """After an update: install packages the new version needs for the components already installed.

    `--inexact` never removes anything. Failures are reported, not fatal – setup.cmd can repair it.
    """
    import os
    import subprocess
    uv = os.environ.get("VC_UV") or str(root / "uv.exe")
    extras = installed_extras()
    cmd = [uv, "sync", "--frozen", "--inexact", "--project", str(root)] + [a for x in extras for a in ("--extra", x)]
    try:
        code = subprocess.run(cmd, env={**os.environ, **layout.environment(root)}).returncode
    except OSError as e:
        code = str(e)
    if code != 0:
        _log.warning("could not update the installed components (%s) – run setup.cmd once", code)


def outdated_workers(watcher_port: int, target: str) -> list[str]:
    """Paired workers older than `target`, read from a coordinator running on this computer ([] if none runs)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{watcher_port}/api/status", timeout=3) as r:
            status = json.loads(r.read())
    except (OSError, ValueError):
        return []
    return [f"{w['name']} ({w.get('version') or 'unknown'})" for w in status.get("workers", [])
            if not w.get("version") or _version_tuple(w["version"]) < _version_tuple(target)]


def run(args: argparse.Namespace, watcher_port: int = 5132) -> int:
    """The interactive update."""
    try:
        if args.rollback:
            rollback()
            _log.info("previous version restored – run setup.cmd if it needs other components")
            return 0
        rel = latest()
        print(f"Installed: {__version__}   Latest: {rel['version']}   Download: {rel['size'] / 1024 ** 2:.1f} MB")
        if not is_newer(rel["version"]):
            print("You already have the latest version.")
            return 0
        print("\nChanges:\n" + rel["notes"][:3000])
        behind = outdated_workers(watcher_port, rel["version"])
        if behind:  # order matters: workers first, the coordinator last
            print("\nThis computer runs the coordinator, and these workers are not updated yet:\n  "
                  + "\n  ".join(behind) + "\nUpdate them first (watcher: 'Update workers'), then the coordinator.")
        if input("\nUpdate now? Your settings, pairings, voices and output stay. [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
        rel["version"] = download_and_install(rel)
    except (UpdateError, OSError, ValueError, KeyError) as e:
        _log.error("update not installed: %s", e)
        return 1
    _log.info("updated to %s – run setup.cmd once so new components can be installed; "
              "'crucible update --rollback' goes back", rel["version"])
    return 0
