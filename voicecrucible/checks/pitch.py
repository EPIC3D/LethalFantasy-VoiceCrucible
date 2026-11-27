"""Pitch check: median voice pitch must exist (something voiced) and stay under a ceiling (not childish/squeaky).

Settings: max_f0 (380 Hz).
"""

from __future__ import annotations

import numpy as np

from voicecrucible.checks.base import CHECK_RATE, Candidate, Check, limit as limit_for
from voicecrucible.core.jobs import CheckResult


class PitchCheck(Check):
    """Median F0 with librosa's pYIN."""

    name = "pitch"

    def run(self, take: Candidate) -> CheckResult:
        import librosa
        f0, voiced, _ = librosa.pyin(take.audio16k, fmin=80, fmax=600, sr=CHECK_RATE)
        f0 = f0[voiced & ~np.isnan(f0)]
        median = float(np.median(f0)) if len(f0) else 0.0
        limit = limit_for(self.settings, take.line, "max_f0", 380.0)
        if median <= 0:
            return CheckResult(self.name, False, "no voiced speech found", 0.0)
        ok = median <= limit
        return CheckResult(self.name, ok, "" if ok else f"pitch too high ({median:.0f} Hz > {limit:.0f})",
                           round(median, 1))


CHECK = PitchCheck
