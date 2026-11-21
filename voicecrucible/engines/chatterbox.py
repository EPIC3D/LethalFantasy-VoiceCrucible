"""Chatterbox TTS (Resemble AI, MIT): zero-shot voice from a reference clip, emotion via 'exaggeration'.

Line params: exaggeration (0.25–1.2, more = more expressive), cfg_weight (0.2–0.7, less = slower, freer).
Chatterbox renders one line at a time; the batch is a loop. Output carries Chatterbox's own watermark.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from voicecrucible.core.jobs import Line
from voicecrucible.engines.base import Audio, Engine, OutOfMemory, seed_for


class ChatterboxEngine(Engine):
    """Chatterbox with per-line reference voice, exaggeration and cfg weight."""

    name = "chatterbox"

    def __init__(self) -> None:
        self._model = None
        self._torch = None

    def load(self, device: str) -> None:
        """Load the model (downloaded on first use into the Hugging Face cache)."""
        import torch
        from chatterbox.tts import ChatterboxTTS
        self._torch = torch
        self._model = ChatterboxTTS.from_pretrained(device=device)

    def render(self, lines: list[Line], voices: dict[str, Path]) -> list[Audio]:
        """Render each line with its own seed, reference voice and sliders."""
        out = []
        for line in lines:
            self._torch.manual_seed(seed_for(line))
            try:
                wav = self._model.generate(line.text, audio_prompt_path=str(voices[line.voice]),
                                           exaggeration=float(line.params.get("exaggeration", 0.5)),
                                           cfg_weight=float(line.params.get("cfg_weight", 0.5)))
            except self._torch.cuda.OutOfMemoryError as e:
                raise OutOfMemory(str(e)) from e
            out.append(Audio(wav.squeeze(0).cpu().numpy().astype(np.float32), self._model.sr))
        return out

    def unload(self) -> None:
        """Free the model and GPU memory."""
        self._model = None
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()


ENGINE = ChatterboxEngine
