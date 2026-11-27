"""`crucible diagnose`: the facts needed to fix a bug, ready to paste into a GitHub issue.

Only technical data: versions, OS, GPU/driver/VRAM, settings, recent log lines. IP addresses, the computer
name, the user name and home folder, tokens and keys are removed before anything is shown or saved.
"""

from __future__ import annotations

import getpass
import importlib.metadata
import platform
import re
import socket
from dataclasses import asdict
from pathlib import Path

from voicecrucible import __version__
from voicecrucible.core.config import Config
from voicecrucible.installer import gpucheck, layout

_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_SECRET = re.compile(r"(?i)\b(token|api[_-]?key|bearer|secret|password)\b([\"'=: \t]+)[^\s'\"]+")


def redact(text: str) -> str:
    """Remove personal or secret data from a text."""
    out = _IP.sub("<ip>", text)
    out = _SECRET.sub(r"\1\2<hidden>", out)
    home = str(Path.home())
    for value, label in ((home, "<home>"), (home.replace("\\", "/"), "<home>"), (socket.gethostname(), "<computer>"),
                         (getpass.getuser(), "<user>")):
        if value and len(value) > 2:
            out = re.sub(re.escape(value), label, out, flags=re.IGNORECASE)
    return out


def _version(pkg: str) -> str:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def collect(cfg: Config, log_lines: int = 60) -> str:
    """The diagnose report as text (already redacted)."""
    parts = [f"Voice Crucible {__version__}", f"OS: {platform.system()} {platform.release()} ({platform.version()})",
             f"Python: {platform.python_version()}"]
    for pkg in ("torch", "chatterbox-tts", "qwen-tts", "openai-whisper", "transformers"):
        parts.append(f"{pkg}: {_version(pkg)}")
    try:
        import torch
        parts.append(f"CUDA available: {torch.cuda.is_available()} (torch CUDA {torch.version.cuda})")
    except ImportError:
        pass
    parts.append("GPU:")
    parts += ["  " + n for n in gpucheck.check().notes]
    parts.append(f"Seed-VC installed: {(layout.runtime() / 'components' / 'seed-vc' / '.venv').exists()}")
    parts.append(f"Breeze installed: {(layout.runtime() / 'components' / 'breeze' / '.venv').exists()}")
    parts.append("Settings:")
    for name, section in asdict(cfg).items():
        if isinstance(section, dict):
            parts.append(f"  [{name}] " + ", ".join(f"{k}={v!r}" for k, v in section.items()))
    logs = sorted(cfg.path(cfg.paths.log_dir).glob("*.log"), key=lambda p: p.stat().st_mtime)
    for logfile in [p for p in logs if not p.name.startswith("diagnose")][-2:]:
        tail = logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-log_lines:]
        parts += [f"--- last lines of {logfile.name} ---"] + tail
    return redact("\n".join(parts))


def run(cfg: Config) -> int:
    """Print the report and save it to diagnose.txt."""
    text = collect(cfg)
    out = cfg.path(cfg.paths.log_dir) / "diagnose.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nSaved to {redact(str(out))} – please check it and paste it into your GitHub issue.")
    return 0
