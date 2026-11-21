"""Engine interface and registry. An engine turns a batch of lines into audio, one result per line.

Engines are imported only when used, so heavy libraries (torch, models) load only on machines that need them.
To add an engine: implement `Engine` in a new module (exporting ENGINE = the class) and add it to `_MODULES`.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voicecrucible.core.jobs import Line

_MODULES = {
    "test": "voicecrucible.engines.tone",
    "chatterbox": "voicecrucible.engines.chatterbox",
    "qwen": "voicecrucible.engines.qwen",
    "qwen_vc": "voicecrucible.engines.qwen_vc",
}


class OutOfMemory(RuntimeError):
    """The GPU ran out of memory for this batch; the runner retries with a smaller batch."""


@dataclass
class Audio:
    """Rendered audio of one line: mono float32 samples."""

    samples: np.ndarray
    sample_rate: int


class Engine(ABC):
    """Base class of all engines."""

    name: str = ""
    batch_lines: int | None = None  # lines per render() call; 1 = no real batching (lets a stop take effect sooner)

    @abstractmethod
    def load(self, device: str) -> None:
        """Load models onto `device` ("cuda", "cpu", …)."""

    @abstractmethod
    def render(self, lines: list[Line], voices: dict[str, Path]) -> list[Audio]:
        """Render a batch; one Audio per line, in order. `voices` maps line.voice to the reference file.
        Raise OutOfMemory on GPU out-of-memory."""

    def unload(self) -> None:
        """Free models and GPU memory."""


def available() -> list[str]:
    """Names of all known engines."""
    return sorted(_MODULES)


def create(name: str) -> Engine:
    """Instantiate an engine by name (imports its module on first use)."""
    if name not in _MODULES:
        raise ValueError(f"unknown engine '{name}' (known: {', '.join(available())})")
    return importlib.import_module(_MODULES[name]).ENGINE()


def seed_for(line: Line) -> int:
    """Deterministic seed per line and attempt: the same take is reproducible, a retry sounds different."""
    import zlib
    return zlib.crc32(line.file_stem.encode()) + 1000 * (line.attempt - 1)
