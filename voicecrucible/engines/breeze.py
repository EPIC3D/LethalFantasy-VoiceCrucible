"""Breeze TTS 2 (BreezeBlue) in "Voice Direction" mode: the character's reference voice + its exact transcript,
steered by a natural-language acting instruction. User verdict (2026-11-25): cleaner and better acting than
Chatterbox, consistent voice; best with the long director instruction and cfg_scale 3.25.

Licences: the Breeze code is Apache-2.0; the model weights AND the audio they generate are for research and
non-commercial use only (BreezeBlue licence). It is an optional component in its own folder and Python environment
(env var VOICECRUCIBLE_BREEZE_DIR, set by the worker from the config). This module starts Breeze's own HTTP server
there, bound to 127.0.0.1 on a free port (nothing is reachable from the network), and talks to it per line.

Line params: instruction, cfg_scale, ref_text (transcript of the reference voice).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np

from voicecrucible.core.jobs import Line
from voicecrucible.engines.base import Audio, Engine, OutOfMemory, seed_for, spoken_text

ENV_DIR = "VOICECRUCIBLE_BREEZE_DIR"
MODEL = "BreezeBlue/Breeze-TTS-2"
MODEL_REVISION = "3e28c5151381a722f1d8661b4118c298caa77aa4"  # pinned weights (2026-11-25)
SAMPLE_RATE = 24000
MIN_VRAM_MB = 11000  # the model needs ~7.7 GiB plus the director's CFG pass; BreezeBlue recommends 12 GB
START_TIMEOUT = 900  # first start downloads the model (7.7 GB)


class BreezeNotInstalled(RuntimeError):
    """The optional Breeze component is missing."""


def _python(folder: Path) -> Path:
    """The Python of Breeze's own environment."""
    return folder / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def cannot_run() -> str:
    """Why this machine cannot run Breeze ('' = it can). The worker then asks for other engines' lines only."""
    folder = Path(os.environ.get(ENV_DIR, ""))
    if not (folder / "breeze_infer" / "api.py").exists() or not _python(folder).exists():
        return "component not installed"
    from voicecrucible.worker import gpu
    gpus = gpu.query()
    if not gpus:
        return "no NVIDIA GPU"
    if gpus[0]["memory_total_mb"] < MIN_VRAM_MB:
        return f"GPU has {gpus[0]['memory_total_mb'] / 1024:.0f} GB, Breeze needs 12 GB"
    return ""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BreezeEngine(Engine):
    """Breeze TTS 2 through its local API server (started and stopped with the engine)."""

    name = "breeze"
    batch_lines = 4  # one request per line (each line has its own instruction); small jobs keep stops quick

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._url = ""
        self._log = None
        self._refs: dict[Path, bytes] = {}

    def load(self, device: str) -> None:
        """Check the component and the GPU, start the server, wait until the model is loaded."""
        folder = Path(os.environ.get(ENV_DIR, ""))
        if not (folder / "breeze_infer" / "api.py").exists() or not _python(folder).exists():
            raise BreezeNotInstalled(f"Breeze TTS 2 (optional component) not found in '{folder}' – install it with "
                                     "'crucible setup' (component 'breeze') or choose another engine")
        if device != "cuda":
            raise RuntimeError("Breeze TTS 2 needs an NVIDIA GPU (12 GB or more)")
        from voicecrucible.worker import gpu
        gpus = gpu.query()
        if gpus and gpus[0]["memory_total_mb"] < MIN_VRAM_MB:
            raise RuntimeError(f"Breeze TTS 2 needs a GPU with 12 GB or more – this one has "
                               f"{gpus[0]['memory_total_mb'] / 1024:.0f} GB; render 'breeze' lines on a bigger worker")
        port = _free_port()
        self._url = f"http://127.0.0.1:{port}"
        self._log = tempfile.NamedTemporaryFile("w", prefix="breeze_", suffix=".log", delete=False, encoding="utf-8")
        self._proc = subprocess.Popen(
            [str(_python(folder)), "-m", "breeze_infer.api", MODEL, "--revision", MODEL_REVISION,
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=folder, stdout=self._log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
        deadline = time.time() + START_TIMEOUT
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"Breeze TTS 2 server stopped while starting – see {self._log.name}")
            try:
                with urllib.request.urlopen(self._url + "/health", timeout=5) as r:
                    if r.status == 200:
                        return
            except (OSError, urllib.error.HTTPError):
                pass
            time.sleep(3)
        self.unload()
        raise RuntimeError(f"Breeze TTS 2 server did not start within {START_TIMEOUT // 60} minutes – "
                           f"see {self._log.name}")

    def render(self, lines: list[Line], voices: dict[str, Path]) -> list[Audio]:
        """One request per line: reference voice + transcript, text, instruction, cfg, a seed per take."""
        out = []
        for line in lines:
            ref = voices[line.voice]
            if ref not in self._refs:
                self._refs[ref] = Path(ref).read_bytes()
            p = line.params
            fields = {"text": spoken_text(line), "ref_text": str(p.get("ref_text", "")),
                      "seed": str(seed_for(line) % 2_147_483_647), "cfg_scale": str(p.get("cfg_scale", 1.0))}
            if p.get("instruction"):
                fields["instruction"] = str(p["instruction"])
            pcm = self._post(fields, self._refs[ref], Path(ref).name)
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            out.append(Audio(samples, SAMPLE_RATE))
        return out

    def _post(self, fields: dict[str, str], ref: bytes, ref_name: str) -> bytes:
        """multipart/form-data POST to /v1/audio/speech; returns 24 kHz s16le PCM."""
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in fields.items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="ref_audio"; filename="{ref_name}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode() + ref + f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(self._url + "/v1/audio/speech", b"".join(parts),
                                     {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            if "out of memory" in detail.lower():
                raise OutOfMemory(detail) from None
            raise RuntimeError(f"Breeze TTS 2 error {e.code}: {detail}") from None

    def unload(self) -> None:
        """Stop the server (frees the GPU)."""
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None
        self._refs.clear()


ENGINE = BreezeEngine


def model_info(url: str) -> dict:
    """GET /v1/model of a running Breeze server (diagnostics)."""
    with urllib.request.urlopen(url + "/v1/model", timeout=5) as r:
        return json.loads(r.read())
