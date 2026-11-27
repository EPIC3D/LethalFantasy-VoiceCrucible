"""GPU information for heartbeats and device choice. Uses nvidia-smi when present; works without a GPU too."""

from __future__ import annotations

import shutil
import subprocess

_QUERY = "name,memory.total,memory.used,utilization.gpu,temperature.gpu"


def query() -> list[dict]:
    """One dict per NVIDIA GPU (name, memory_total_mb, memory_used_mb, utilization_pct, temperature_c when the
    driver reports it); [] if unavailable."""
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
        if len(parts) != 5:
            continue
        try:
            g = {"name": parts[0], "memory_total_mb": int(parts[1]), "memory_used_mb": int(parts[2]),
                 "utilization_pct": int(parts[3])}
        except ValueError:
            continue
        try:  # "[N/A]" on some cards; newer drivers report decimals ("55.85")
            g["temperature_c"] = round(float(parts[4]))
        except ValueError:
            pass
        gpus.append(g)
    _add_thermal(exe, gpus)
    return gpus


_THERMAL = "clocks_event_reasons.hw_thermal_slowdown,clocks_event_reasons.sw_thermal_slowdown,temperature.gpu.tlimit"


def _add_thermal(exe: str, gpus: list[dict]) -> None:
    """The card's own limits: thermal_slowdown = it is slowing down because of heat right now; headroom_c = degrees
    left before it does. Separate query: older drivers do not know these fields (then they are simply missing)."""
    try:
        out = subprocess.run([exe, f"--query-gpu={_THERMAL}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for g, row in zip(gpus, out.strip().splitlines(), strict=False):  # same GPU order as the first query
        parts = [p.strip() for p in row.split(",")]
        if len(parts) != 3:
            continue
        g["thermal_slowdown"] = parts[0] == "Active" or parts[1] == "Active"  # else "Not Active" or "[N/A]"
        try:
            g["headroom_c"] = round(float(parts[2]))
        except ValueError:
            pass


def default_device() -> str:
    """'cuda' when an NVIDIA GPU is visible, else 'cpu' (engines refine this in their own load())."""
    return "cuda" if query() else "cpu"
