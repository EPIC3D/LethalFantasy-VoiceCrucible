"""Check interface, the take being checked, the check registry and the runner for a set of checks.

Settings come from the coordinator with each job (thresholds, names), so all workers judge alike.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np

from voicecrucible.core.jobs import CheckResult, Line

_MODULES = {
    "words": "voicecrucible.checks.words",
    "similarity": "voicecrucible.checks.similarity",
    "quality": "voicecrucible.checks.quality",
    "pitch": "voicecrucible.checks.pitch",
}
CHECK_RATE = 16000  # all checks work on 16 kHz audio


@dataclass
class Candidate:
    """A rendered take of a line plus everything the checks need."""

    line: Line
    samples: np.ndarray
    sample_rate: int
    reference: Path | None = None
    extra: dict = field(default_factory=dict)

    @cached_property
    def audio16k(self) -> np.ndarray:
        """The take resampled to 16 kHz (computed once, shared by all checks)."""
        if self.sample_rate == CHECK_RATE:
            return self.samples
        import librosa
        return librosa.resample(self.samples, orig_sr=self.sample_rate, target_sr=CHECK_RATE)


class Check(ABC):
    """Base class of all checks."""

    name: str = ""

    def __init__(self, settings: dict):
        self.settings = settings

    def load(self, device: str) -> None:
        """Load models (optional)."""

    @abstractmethod
    def run(self, take: Candidate) -> CheckResult:
        """Judge one take."""


def limit(settings: dict, line: Line, key: str, default: float) -> float:
    """A check threshold for this line: the `intense_<key>` value for strong emotions (shouting, strain), else
    `<key>`. Strong emotions sound far from the calm reference voice without being wrong. A line can carry its own
    thresholds from its engine (params "check_<key>" / "check_intense_<key>"): Breeze keeps the voice much steadier
    than Chatterbox, so 0.60 let another speaker's voice through (heard: an Akipo line in Red's voice)."""
    own = line.params or {}
    if line.emotion in settings.get("intense_expressions", ()):
        if f"check_intense_{key}" in own:
            return float(own[f"check_intense_{key}"])
        if f"intense_{key}" in settings:
            return float(settings[f"intense_{key}"])
    if f"check_{key}" in own:
        return float(own[f"check_{key}"])
    return float(settings.get(key, default))


def available() -> list[str]:
    """Names of all known checks."""
    return sorted(_MODULES)


class CheckSet:
    """The checks a job asks for, loaded once and reused while the settings stay the same."""

    def __init__(self, device: str):
        self.device = device
        self._checks: list[Check] = []
        self._key = None

    def configure(self, settings: dict) -> None:
        """(Re)load the checks named in settings['enabled'] if the settings changed."""
        key = repr(sorted(settings.items()))
        if key == self._key:
            return
        self._checks = []
        for name in settings.get("enabled", []):
            if name not in _MODULES:
                raise ValueError(f"unknown check '{name}' (known: {', '.join(available())})")
            check = importlib.import_module(_MODULES[name]).CHECK(settings)
            check.load(self.device)
            self._checks.append(check)
        self._key = key

    def word_times(self, samples: np.ndarray, sample_rate: int) -> list[dict] | None:
        """Whisper word timing of a take (for cutting a primed retake); None when the words check is not loaded."""
        words = next((c for c in self._checks if c.name == "words"), None)
        return words.word_times(samples, sample_rate) if words is not None else None

    def run(self, take: Candidate) -> list[CheckResult]:
        """Run every check; all are run so the report lists every problem of a take."""
        return [c.run(take) for c in self._checks]


def summary(results: list[CheckResult]) -> tuple[bool, str]:
    """Passed flag and a short reason listing the failed checks."""
    failed = [f"{r.check}: {r.reason}" for r in results if not r.passed]
    return not failed, "; ".join(failed)
