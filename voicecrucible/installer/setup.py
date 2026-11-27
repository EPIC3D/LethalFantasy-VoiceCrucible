"""`crucible setup`: check the machine, show exactly what will be downloaded, ask, install, write INSTALLED.txt.

Everything goes into the install folder (runtime\\...). Nothing is installed system-wide, no admin rights,
no PATH changes, no background service. Running setup again changes the selection (adds or removes parts).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from voicecrucible.core import log
from voicecrucible.core.config import Config
from voicecrucible.installer import disk, gpucheck, inventory, layout, manifest

_log = log.get("setup")
OPTIONAL = ("qwen", "seedvc", "breeze")
CU128_INDEX = "https://download.pytorch.org/whl/cu128"


def _ask(question: str, default: bool, assume_yes: bool) -> bool:
    """Yes/no question on the console (the default answer is used with --yes)."""
    if assume_yes:
        return default
    answer = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not answer else answer in ("y", "yes", "i", "igen")


def choose(args: argparse.Namespace, gpu_ok: bool) -> set[str]:
    """Components to install: from --components, else asked (defaults depend on the GPU)."""
    if args.components:
        return {c.strip() for c in args.components.split(",") if c.strip()}
    if not gpu_ok:
        print("No supported GPU – installing only the coordinator/watcher part.")
        return set()
    wanted = {"checks", "chatterbox"}
    if _ask("Also install the acting engine (Qwen3-TTS, ~4.6 GB)?", False, args.yes):
        wanted.add("qwen")
        if _ask("Also install Seed-VC voice conversion (GPL-3.0, ~6 GB) – needed for acting packs?", False, args.yes):
            wanted.add("seedvc")
    if _ask("Also install Breeze TTS 2 (needs a 12 GB+ GPU, ~13 GB; model and audio for NON-COMMERCIAL use only)?",
            False, args.yes):
        wanted.add("breeze")
    return wanted


def _run(cmd: list[str], env: dict[str, str]) -> None:
    """Run an installer step directly in the console, so its progress bars stay visible.

    The log records the command and its result; what was installed ends up in INSTALLED.txt.
    """
    _log.info("running: %s", " ".join(cmd))
    code = subprocess.run(cmd, env=env).returncode
    _log.info("finished with exit code %d", code)
    if code != 0:
        raise RuntimeError(f"step failed (exit code {code}): {cmd[0]} {cmd[1]}")


def _download(url: str, target: Path) -> None:
    """Download a file with a simple progress line."""
    def progress(blocks: int, block_size: int, total: int) -> None:
        done = blocks * block_size
        text = f"{done / 1024 ** 2:.0f} / {total / 1024 ** 2:.0f} MB" if total > 0 else f"{done / 1024 ** 2:.0f} MB"
        print(f"\r  downloading {target.name}: {text}   ", end="", flush=True)
    urllib.request.urlretrieve(url, target, progress)
    print()


def _install_component(comp: manifest.Component, uv: str, env: dict[str, str], root: Path) -> None:
    """Download a separate component (Seed-VC, Breeze) at its pinned commit, verify the checksum, unpack, and create
    its own environment in runtime/components/<folder>."""
    name = comp.extra["folder"]
    target = layout.runtime(root) / "components" / name
    downloads = layout.runtime(root) / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / f"{name}-{comp.extra['commit'][:12]}.zip"
    if not archive.exists():
        _log.info("downloading %s from %s", name, comp.extra["zip_url"])
        _download(comp.extra["zip_url"], archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != comp.extra["zip_sha256"]:
        archive.unlink()
        raise RuntimeError(f"{name} download does not match the expected checksum – not installed")
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(archive) as z:
        top = z.namelist()[0].split("/")[0]
        for member in z.infolist():
            rel = member.filename[len(top) + 1:]
            if not rel or member.is_dir():
                continue
            out = (target / rel).resolve()
            if target.resolve() not in out.parents:  # no path tricks inside the archive
                raise RuntimeError(f"unsafe path in archive: {member.filename}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(member))
    venv = target / ".venv"
    # --no-config: the component has its own pinned versions; Voice Crucible's pyproject overrides must not apply
    _run([uv, "venv", "--no-config", str(venv), "--python", comp.extra.get("python", "3.12")], env)
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    overrides = ["--overrides", str(root / comp.extra["overrides"])] if comp.extra.get("overrides") else []
    _run([uv, "pip", "install", "--no-config", "--python", str(py), "-r", str(root / comp.extra["requirements"]),
          *overrides, "--extra-index-url", CU128_INDEX, "--index-strategy", "unsafe-best-match"], env)


def run(cfg: Config, args: argparse.Namespace) -> int:
    """The interactive setup."""
    root = layout.ROOT
    print(f"Voice Crucible setup – install folder: {root}\n"
          "Nothing is installed outside this folder; no admin rights, no PATH changes, no background service.\n")
    report = gpucheck.check()
    print("GPU:")
    for note in report.notes:
        print("  " + note)
    components = manifest.load()
    try:
        selected = manifest.resolve(components, choose(args, report.supported))
    except ValueError as e:
        _log.error("%s (known: %s)", e, ", ".join(components))
        return 1
    print("\nWill be downloaded and installed (what each part does: docs\\DOWNLOADS.md):\n" + manifest.table(selected))
    kind = disk.drive_type(root)
    free = disk.free_gb(root)
    need = sum(c.disk_gb for c in selected)
    print(f"\nTarget drive: {kind} – {disk.advice(kind)}\nFree space: {free:.0f} GB, needed: ~{need:.1f} GB")
    if free < need * 1.1:
        _log.error("not enough free space on this drive – free up space or move the Voice Crucible folder")
        return 1
    if not args.yes and not _ask("\nStart the download and installation?", False, False):
        print("Nothing was installed.")
        return 1
    uv = os.environ.get("VC_UV") or shutil.which("uv")
    if not uv:
        _log.error("uv not found – start setup with setup.cmd")
        return 1
    env = {**os.environ, **layout.environment(root)}
    keys = [c.key for c in selected]
    try:
        extras = [x for c in selected for x in c.extras]
        _run([uv, "sync", "--frozen", "--project", str(root)] + [a for x in extras for a in ("--extra", x)], env)
        for key in ("seedvc", "breeze"):
            if key in keys:
                _install_component(components[key], uv, env, root)
    except (RuntimeError, OSError) as e:
        _log.error("installation stopped: %s – details in the install log (logs\\setup_*.log)", e)
        return 1
    path = inventory.write(root, keys)
    from voicecrucible.installer import setupstate
    setupstate.record(root)
    _log.info("done. Installed parts and their folders: %s", path)
    return 0
