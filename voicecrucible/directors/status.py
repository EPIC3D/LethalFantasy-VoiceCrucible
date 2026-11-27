"""Progress of a running `crucible direct`, shared with the coordinator through a small JSON file in the work folder.

The coordinator reads it to show the directing in the watcher and to keep the worker on the director's PC in
standby while its GPU runs the language model. No network port is needed for this.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from pathlib import Path

FILE = "director_status.json"
STALE_AFTER_SECONDS = 600  # a crashed `direct` must not hold a worker forever (one scene can take minutes)


def write(work_dir: Path, status: dict) -> None:
    """Replace the status file atomically."""
    work_dir.mkdir(parents=True, exist_ok=True)
    tmp = work_dir / (FILE + ".tmp")
    tmp.write_text(json.dumps({**status, "updated": time.time()}), encoding="utf-8")
    tmp.replace(work_dir / FILE)


def read(work_dir: Path) -> dict | None:
    """The last status, with `active` = running and recently updated; None when no directing ever ran here."""
    try:
        data = json.loads((work_dir / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    fresh = time.time() - float(data.get("updated", 0)) < STALE_AFTER_SECONDS
    data["active"] = bool(data.get("running")) and fresh
    return data


def host_addresses(host: str) -> set[str]:
    """IP addresses of the director's host, to recognise the worker running on the same PC."""
    if not host:
        return set()
    if host in ("localhost", "127.0.0.1", "::1"):
        return {"127.0.0.1", "::1"}
    try:
        ipaddress.ip_address(host)
        return {host}
    except ValueError:
        pass
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return set()
