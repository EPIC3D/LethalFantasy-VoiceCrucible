"""GPU information for heartbeats and device choice. Uses nvidia-smi when present; works without a GPU too."""

from __future__ import annotations

import shutil
import subprocess

_QUERY = "name,memory.total,memory.used,utilization.gpu"


def query() -> list[dict]:
    """One dict per NVIDIA GPU (name, memory_total_mb, memory_used_mb, utilization_pct); [] if unavailable."""
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return []
    try:
        out = subprocess.run([exe, f"--query-gpu={_QUERY}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for row in out.strip().splitlines():
        parts = [p.strip() for p in row.split(",")]
        if len(parts) != 4:
            continue
        try:
            gpus.append({"name": parts[0], "memory_total_mb": int(parts[1]), "memory_used_mb": int(parts[2]),
                         "utilization_pct": int(parts[3])})
        except ValueError:
            continue
    return gpus


def default_device() -> str:
    """'cuda' when an NVIDIA GPU is visible, else 'cpu' (engines refine this in their own load())."""
    return "cuda" if query() else "cpu"
