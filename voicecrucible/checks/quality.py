"""Audio quality estimate (UTMOS, via SpeechMOS): rejects noisy, broken or garbled takes.

Settings: min_mos (2.0). The model code comes from torch.hub, pinned to tarepan/SpeechMOS v1.2.0 (MIT).
"""

from __future__ import annotations

from voicecrucible.checks.base import CHECK_RATE, Candidate, Check, limit as limit_for
from voicecrucible.core.jobs import CheckResult

_HUB_REPO = "tarepan/SpeechMOS:v1.2.0"


class QualityCheck(Check):
    """Predicted mean opinion score (1 = bad … 5 = excellent)."""

    name = "quality"

    def load(self, device: str) -> None:
        import torch
        self._torch = torch
        self._device = device
        self._model = torch.hub.load(_HUB_REPO, "utmos22_strong", trust_repo=True).to(device).eval()

    def run(self, take: Candidate) -> CheckResult:
        from voicecrucible.checks.words import speechless
        if speechless(take.line.text):  # the speech-quality model rates any hum as poor (heard good hums: MOS 1.3-1.9)
            return CheckResult(self.name, True, "", None)
        with self._torch.no_grad():
            wave = self._torch.from_numpy(take.audio16k).unsqueeze(0).to(self._device)
            mos = float(self._model(wave, CHECK_RATE).item())
        limit = limit_for(self.settings, take.line, "min_mos", 2.0)
        return CheckResult(self.name, mos >= limit, f"poor audio (MOS {mos:.2f} < {limit})" if mos < limit else "",
                           round(mos, 3))


CHECK = QualityCheck
