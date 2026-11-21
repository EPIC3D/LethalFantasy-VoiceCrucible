"""Speaker similarity (resemblyzer): does the take sound like the character's reference voice?

Settings: min_similarity (0.80).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from voicecrucible.checks.base import Candidate, Check
from voicecrucible.core.jobs import CheckResult


class SimilarityCheck(Check):
    """Cosine similarity of voice embeddings, take vs. reference."""

    name = "similarity"

    def load(self, device: str) -> None:
        from resemblyzer import VoiceEncoder
        self._encoder = VoiceEncoder(device=device)
        self._refs: dict[Path, np.ndarray] = {}

    def _embed(self, samples16k: np.ndarray) -> np.ndarray:
        from resemblyzer import preprocess_wav
        return self._encoder.embed_utterance(preprocess_wav(samples16k, source_sr=16000))

    def run(self, take: Candidate) -> CheckResult:
        if take.reference is None:
            return CheckResult(self.name, True, "no reference voice", None)
        if take.reference not in self._refs:
            from resemblyzer import preprocess_wav
            self._refs[take.reference] = self._encoder.embed_utterance(preprocess_wav(take.reference))
        sim = float(np.dot(self._refs[take.reference], self._embed(take.audio16k)))
        limit = self.settings.get("min_similarity", 0.80)
        return CheckResult(self.name, sim >= limit, f"other voice ({sim:.2f} < {limit})" if sim < limit else "",
                           round(sim, 3))


CHECK = SimilarityCheck
