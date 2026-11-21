"""Free space and drive type (HDD / SATA SSD / NVMe) of the install folder's drive."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def free_gb(path: Path) -> float:
    """Free space on the drive holding `path` (or its nearest existing parent)."""
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free / 1024 ** 3


def drive_type(path: Path) -> str:
    """'NVMe', 'SSD', 'HDD' or 'unknown'."""
    try:
        return _windows(path) if sys.platform == "win32" else _linux(path)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return "unknown"


def _windows(path: Path) -> str:
    """Partition -> disk -> physical disk media and bus type, via PowerShell storage cmdlets."""
    letter = path.resolve().drive.rstrip(":")
    if not letter:
        return "unknown"
    script = (f"$d = (Get-Partition -DriveLetter {letter} | Get-Disk).Number; "
              "Get-PhysicalDisk | Where-Object { $_.DeviceId -eq \"$d\" } | "
              "Select-Object MediaType, BusType | ConvertTo-Json")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                         timeout=30).stdout
    info = json.loads(out) if out.strip() else {}
    bus, media = str(info.get("BusType", "")), str(info.get("MediaType", ""))
    if bus in ("17", "NVMe"):
        return "NVMe"
    if media in ("4", "SSD"):
        return "SSD"
    if media in ("3", "HDD"):
        return "HDD"
    return "unknown"


def _linux(path: Path) -> str:
    """Block device of the mount -> /sys/block/<dev>/queue/rotational."""
    dev = os.stat(path if path.exists() else path.parent).st_dev
    major, minor = os.major(dev), os.minor(dev)
    sys_dev = Path(f"/sys/dev/block/{major}:{minor}").resolve()
    disk = sys_dev.parent if (sys_dev / "partition").exists() else sys_dev
    if disk.name.startswith("nvme"):
        return "NVMe"
    rotational = (disk / "queue" / "rotational").read_text().strip()
    return "HDD" if rotational == "1" else "SSD"


def advice(kind: str) -> str:
    """What the drive type means for Voice Crucible."""
    if kind == "HDD":
        return ("HDD: models of several GB load much slower at every start – an SSD/NVMe is recommended. "
                "The output folder may stay on an HDD.")
    if kind == "unknown":
        return "drive type could not be detected"
    return f"{kind}: fine"
