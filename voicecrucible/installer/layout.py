"""Where everything lives inside the install folder. The launchers (*.cmd) set the same environment
variables, so Python, packages, caches and models never land outside this folder (e.g. on C:)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parents[2]  # the install folder (= repository root)


def runtime(root: Path = ROOT) -> Path:
    """Everything that setup downloads."""
    return root / "runtime"


def environment(root: Path = ROOT) -> dict[str, str]:
    """Environment variables that keep uv, Python, model caches inside the install folder."""
    rt = runtime(root)
    return {
        "UV_PYTHON_INSTALL_DIR": str(rt / "python"),
        "UV_CACHE_DIR": str(rt / "uv-cache"),
        "UV_PROJECT_ENVIRONMENT": str(rt / "venv"),
        "UV_PYTHON_PREFERENCE": "only-managed",
        "HF_HOME": str(rt / "models" / "huggingface"),
        "TORCH_HOME": str(rt / "models" / "torch"),
        "XDG_CACHE_HOME": str(rt / "models"),  # Whisper downloads to $XDG_CACHE_HOME/whisper
    }


def folders(root: Path = ROOT) -> dict[str, Path]:
    """The folders listed in INSTALLED.txt with what they hold."""
    rt = runtime(root)
    return {
        "Python interpreter": rt / "python",
        "Python packages (environment)": rt / "venv",
        "Download cache (can be deleted to save space)": rt / "uv-cache",
        "Models (Hugging Face, PyTorch hub, Whisper)": rt / "models",
        "Seed-VC (optional, GPL-3.0)": rt / "components" / "seed-vc",
        "Breeze TTS 2 (optional, non-commercial model)": rt / "components" / "breeze",
    }


def apply(root: Path = ROOT) -> None:
    """Set the environment for this process and its children (used when started without a launcher)."""
    for key, value in environment(root).items():
        os.environ.setdefault(key, value)
