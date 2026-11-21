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

    def run(self, take: Candidate) -> list[CheckResult]:
        """Run every check; all are run so the report lists every problem of a take."""
        return [c.run(take) for c in self._checks]


def summary(results: list[CheckResult]) -> tuple[bool, str]:
    """Passed flag and a short reason listing the failed checks."""
    failed = [f"{r.check}: {r.reason}" for r in results if not r.passed]
    return not failed, "; ".join(failed)
