"""The worker's identity file: its ID, display name and – after pairing – token and pinned coordinator.

Stored as work/worker/identity.json. It contains the token, so it must stay private (it is git-ignored
and never leaves this machine). Deleting it un-pairs the worker.
"""

from __future__ import annotations

import json
import socket
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class WorkerIdentity:
    """Who this worker is and which coordinator it trusts."""

    worker_id: str
    name: str
    token: str = ""
    coordinator_id: str = ""
    fingerprint: str = ""
    host: str = ""
    port: int = 0

    @property
    def paired(self) -> bool:
        """True after a successful `crucible pair`."""
        return bool(self.token and self.fingerprint and self.coordinator_id)


def load(path: Path, name: str = "") -> WorkerIdentity:
    """Read the identity file, or create a new identity (not saved yet) when there is none."""
    if path.exists():
        ident = WorkerIdentity(**json.loads(path.read_text("utf-8")))
    else:
        ident = WorkerIdentity(worker_id=uuid.uuid4().hex, name="")
    ident.name = name or ident.name or socket.gethostname()
    return ident


def save(path: Path, ident: WorkerIdentity) -> None:
    """Write the identity file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(ident), indent=2), encoding="utf-8")
    tmp.replace(path)
