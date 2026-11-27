"""Speaker similarity (resemblyzer): does the take sound like the character's reference voice?

Settings: min_similarity (0.80).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from voicecrucible.checks.base import Candidate, Check, limit as limit_for
from voicecrucible.core.jobs import CheckResult


SHORT_CLIP_SECONDS = 2.0  # below this the voice print is unsteady
SHORT_CLIP_MARGIN = 0.08  # ... so the similarity limit is this much lower
SPEECHLESS_LIMIT = 0.50  # lines without words (a hum, a laugh): measured by ear and score, see run()


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
        limit = limit_for(self.settings, take.line, "min_similarity", 0.80)
        from voicecrucible.checks.words import speechless
        if speechless(take.line.text):  # a hum is far from the speaking voice: good hums 0.52-0.62, noise 0.43
            limit = min(limit, SPEECHLESS_LIMIT)
        elif len(take.audio16k) < SHORT_CLIP_SECONDS * 16000:  # little sound = an unsteady voice print (heard: good
            limit = round(limit - SHORT_CLIP_MARGIN, 2)       # "Look at that!" scored 0.76); words still checked
        return CheckResult(self.name, sim >= limit, f"other voice ({sim:.3f} < {limit})" if sim < limit else "",
                           round(sim, 3))


CHECK = SimilarityCheck
