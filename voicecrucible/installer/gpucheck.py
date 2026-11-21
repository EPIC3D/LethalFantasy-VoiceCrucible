"""Is this machine's GPU supported? Decided by capability (driver, compute capability, VRAM), not by name.

Only hardware facts are read (GPU model, driver version, memory) – nothing personal.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field

MIN_DRIVER = 570  # CUDA 12.8 needs NVIDIA driver 570 or newer
MIN_COMPUTE = 7.5  # Turing (RTX 20 / GTX 16) and newer
BF16_COMPUTE = 8.0  # Ampere (RTX 30) and newer
MIN_VRAM_GB = 6
GOOD_VRAM_GB = 8


@dataclass
class GpuReport:
    """What was found and what it means."""

    nvidia: list[dict] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    supported: bool = False
    notes: list[str] = field(default_factory=list)


def _nvidia() -> list[dict]:
    """NVIDIA GPUs from nvidia-smi: name, driver, VRAM (MB), compute capability."""
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total,compute_cap",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10,
                             check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for row in out.strip().splitlines():
        parts = [p.strip() for p in row.split(",")]
        if len(parts) == 4:
            try:
                gpus.append({"name": parts[0], "driver": parts[1], "vram_mb": int(parts[2]),
                             "compute": float(parts[3])})
            except ValueError:
                continue
    return gpus


def _other_adapters() -> list[str]:
    """Names of non-NVIDIA display adapters (Windows only; empty elsewhere)."""
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [n.strip() for n in out.splitlines() if n.strip() and "nvidia" not in n.lower()]


def evaluate(nvidia: list[dict], other: list[str]) -> GpuReport:
    """Judge the found hardware (pure function, easy to test)."""
    r = GpuReport(nvidia=nvidia, other=other)
    for g in nvidia:
        major = int(g["driver"].split(".")[0]) if g["driver"].split(".")[0].isdigit() else 0
        vram = round(g["vram_mb"] / 1024)  # an "8 GB" card reports slightly less than 8192 MB
        if g["compute"] < MIN_COMPUTE:
            r.notes.append(f"{g['name']}: too old for the engines (GTX 10 and older are not supported)")
            continue
        if major < MIN_DRIVER:
            r.notes.append(f"{g['name']}: driver {g['driver']} is too old – install NVIDIA driver {MIN_DRIVER} or newer "
                           "(https://www.nvidia.com/Download/index.aspx), then run setup again")
            continue
        if vram < MIN_VRAM_GB:
            r.notes.append(f"{g['name']}: {vram:.0f} GB VRAM is not enough for the engines (minimum {MIN_VRAM_GB} GB)")
            continue
        r.supported = True
        speed = "fp16/fp32 (no bf16 – slower)" if g["compute"] < BF16_COMPUTE else "bf16"
        size = "small batches" if vram < GOOD_VRAM_GB else "full speed" if vram >= 12 else "good"
        r.notes.append(f"{g['name']}: supported – {vram:.0f} GB VRAM ({size}), {speed}, driver {g['driver']}")
    for name in other:
        low = name.lower()
        if "amd" in low or "radeon" in low:
            r.notes.append(f"{name}: AMD – experimental only (PyTorch ROCm), not installed by setup")
        elif "intel" in low and "arc" in low:
            r.notes.append(f"{name}: Intel Arc – experimental only (PyTorch XPU), not installed by setup")
    if not r.supported:
        r.notes.append("No supported NVIDIA GPU: this machine can run the coordinator and the watcher; "
                       "rendering needs a worker with a supported NVIDIA card")
    return r


def check() -> GpuReport:
    """Inspect this machine."""
    return evaluate(_nvidia(), _other_adapters())
