"""Chatterbox TTS (Resemble AI, MIT): zero-shot voice from a reference clip, emotion via 'exaggeration'.

Line params: exaggeration (0.25–1.2, more = more expressive), cfg_weight (0.2–0.7, less = slower, freer).
Chatterbox renders one line at a time; the batch is a loop. Output carries Chatterbox's own watermark.
"""

from __future__ import annotations

import re

from pathlib import Path

import numpy as np

from voicecrucible.core.jobs import Line
from voicecrucible.engines.base import Audio, Engine, OutOfMemory, seed_for, spoken_text


SHORT_LINE_WORDS = 2  # lines this short ("Mm-hmm", "Definitely") ...
SHORT_MAX_EXAGGERATION = 0.5  # ... turn into noise with strong emotion settings (heard with Red's 0.7)
SHORT_MIN_CFG = 0.5


def longer_sound(text: str, attempt: int, last_take_text: str = "") -> str:
    """Lines without words ("Mm-hmm", "Ahh!"): each new take stretches the sound a bit more – heard: a quick
    "Mm-hmm" came out as noise, "Mmm-hmmm..." sounded human. The last take says `last_take_text` instead when the
    profile has one for this sound ("Yes.", "That is funny!"). Lines with words are returned unchanged."""
    from voicecrucible.checks.words import speechless
    extra = (attempt - 1) % 3
    if not extra or not speechless(text):
        return text
    if extra == 2 and last_take_text:
        return last_take_text
    stretched = re.sub(r"([A-Za-z])(?![A-Za-z])", lambda m: m.group(1) * (extra + 1), text)  # last letter of a sound
    return re.sub(r"[.!?~]*(\W*)$", lambda m: "..." + m.group(1), stretched, count=1)


def steady_short_line(text: str, exaggeration: float, cfg_weight: float) -> tuple[float, float]:
    """Calmer, steadier settings for one- and two-word lines; longer lines keep their emotion settings."""
    if len(re.findall(r"[\w']+", text)) <= SHORT_LINE_WORDS:
        return min(exaggeration, SHORT_MAX_EXAGGERATION), max(cfg_weight, SHORT_MIN_CFG)
    return exaggeration, cfg_weight


class ChatterboxEngine(Engine):
    """Chatterbox with per-line reference voice, exaggeration and cfg weight."""

    name = "chatterbox"
    batch_lines = 1  # Chatterbox renders line by line anyway

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
            text = longer_sound(spoken_text(line), line.attempt, str(line.params.get("last_take_text", "")))
            exaggeration, cfg_weight = steady_short_line(line.text, float(line.params.get("exaggeration", 0.5)),
                                                         float(line.params.get("cfg_weight", 0.5)))
            try:
                wav = self._model.generate(text, audio_prompt_path=str(voices[line.voice]),
                                           exaggeration=exaggeration, cfg_weight=cfg_weight)
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
