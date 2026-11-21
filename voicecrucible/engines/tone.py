"""Test engine: a short beep per line (length follows the text). Lets you try workers without any model."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from voicecrucible.core.jobs import Line
from voicecrucible.engines.base import Audio, Engine

SAMPLE_RATE = 22050


class ToneEngine(Engine):
    """Renders a sine tone instead of speech."""

    name = "test"

    def load(self, device: str) -> None:
        """Nothing to load."""

    def render(self, lines: list[Line], voices: dict[str, Path]) -> list[Audio]:
        """One soft tone per line, 0.3–3 s long."""
        return [Audio(_tone(min(3.0, 0.3 + 0.03 * len(line.text))), SAMPLE_RATE) for line in lines]


def _tone(seconds: float, freq: float = 440.0) -> np.ndarray:
    """Sine tone with 20 ms fades."""
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.02)
    return (0.25 * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)


ENGINE = ToneEngine
