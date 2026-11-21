"""Voice conversion with Seed-VC (GPL-3.0), run as a separate process – never imported into this program.

Seed-VC is an optional component installed into its own folder with its own Python environment
(env var VOICECRUCIBLE_SEEDVC_DIR, set by the worker from the config). This module starts the GPL bridge
script there and exchanges file paths with it over stdin/stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from voicecrucible.core import audio

BRIDGE = Path(__file__).parents[1] / "vc_bridge" / "seedvc_bridge.py"
ENV_DIR = "VOICECRUCIBLE_SEEDVC_DIR"


class SeedVCNotInstalled(RuntimeError):
    """The optional Seed-VC component is missing."""


def _python(folder: Path) -> Path:
    """The Python of Seed-VC's own environment."""
    return folder / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


class SeedVC:
    """A running Seed-VC bridge process."""

    def __init__(self, folder: Path | None = None):
        folder = folder or Path(os.environ.get(ENV_DIR, ""))
        if not (folder / "seed_vc_wrapper.py").exists() or not _python(folder).exists():
            raise SeedVCNotInstalled(f"Seed-VC (optional component) not found in '{folder}' – "
                                     "install it with 'crucible setup' or choose an engine without voice conversion")
        self._tmp = tempfile.TemporaryDirectory(prefix="vc_", ignore_cleanup_errors=True)
        self._log = open(Path(self._tmp.name) / "seedvc.log", "w", encoding="utf-8")
        self._proc = subprocess.Popen([str(_python(folder)), "-u", str(BRIDGE)], cwd=folder, text=True,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log)
        ready = self._read()
        if not ready.get("ready"):
            raise RuntimeError(f"Seed-VC did not start: {ready}")
        self._n = 0

    def convert(self, samples: np.ndarray, sr: int, ref: Path, steps: int = 50) -> tuple[np.ndarray, int]:
        """Convert one take to the reference voice; returns 44.1 kHz samples with the tail decay trimmed."""
        self._n += 1
        src = Path(self._tmp.name) / f"src_{self._n}.wav"
        out = Path(self._tmp.name) / f"out_{self._n}.wav"
        src.write_bytes(audio.encode(samples, sr, "wav"))
        msg = {"src": str(src.resolve()), "ref": str(Path(ref).resolve()), "out": str(out.resolve()), "steps": steps}
        self._proc.stdin.write(json.dumps(msg) + "\n")  # absolute paths: the bridge runs in the Seed-VC folder
        self._proc.stdin.flush()
        answer = self._read()
        if not answer.get("ok"):
            raise RuntimeError(f"Seed-VC failed: {answer.get('error', answer)}")
        y, out_sr = audio.decode(out.read_bytes())
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        return audio.trim_tail(y, out_sr), out_sr

    def _read(self) -> dict:
        """Next protocol message from the bridge."""
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError("Seed-VC process ended unexpectedly (see its log)")
        return json.loads(line)

    def close(self) -> None:
        """Stop the bridge process and remove temporary files."""
        if self._proc.poll() is None:
            self._proc.stdin.close()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._log.close()
        self._tmp.cleanup()
