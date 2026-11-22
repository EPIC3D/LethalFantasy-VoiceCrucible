"""Qwen3-TTS 1.7B (Alibaba Qwen, Apache-2.0).

Line params:
- mode "design" (default): the voice and acting come from `instruct` (a text direction). Good acting, but
  the voice drifts from line to line – combine with voice conversion (engine "qwen_vc") for a fixed voice.
- mode "clone": the voice comes from the line's reference (x-vector), acting from the text only.
- temperature / subtalker_temperature (0.6 normal, 0.7 intense lines).
- language: Qwen's language name ("English", "Japanese", …), set from the pack language.
Lines are batched (much faster); one seed per batch, taken from the batch's first line.
"""

from __future__ import annotations

from itertools import groupby
from pathlib import Path

import numpy as np

from voicecrucible.core.jobs import Line
from voicecrucible.engines.base import Audio, Engine, OutOfMemory, seed_for, spoken_text

MODELS = {"design": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "clone": "Qwen/Qwen3-TTS-12Hz-1.7B-Base"}
_GEN_KEYS = ("temperature", "subtalker_temperature")


class QwenEngine(Engine):
    """Qwen3-TTS VoiceDesign / clone, loaded per mode on first use."""

    name = "qwen"

    def __init__(self) -> None:
        self._models: dict = {}
        self._prompts: dict[Path, object] = {}
        self._device = "cuda"
        self._torch = None

    def load(self, device: str) -> None:
        """Remember the device; models load lazily (only the modes a job uses)."""
        import torch
        self._torch = torch
        self._device = device

    def _model(self, mode: str):
        """Load a Qwen model once (bf16 where supported, else fp16/fp32)."""
        if mode not in self._models:
            from qwen_tts import Qwen3TTSModel
            t = self._torch
            if self._device == "cuda":
                dtype = t.bfloat16 if t.cuda.is_bf16_supported() else t.float16  # RTX 20 / GTX 16: no bf16
            else:
                dtype = t.float32
            device_map = "cuda:0" if self._device == "cuda" else self._device
            self._models[mode] = Qwen3TTSModel.from_pretrained(MODELS[mode], device_map=device_map, dtype=dtype)
        return self._models[mode]

    def render(self, lines: list[Line], voices: dict[str, Path]) -> list[Audio]:
        """Render in groups of lines that share mode and sampling settings, keeping the input order."""
        results: dict[int, Audio] = {}

        def key(i: int) -> tuple:
            p = lines[i].params
            return (p.get("mode", "design"), p.get("language", "English")) + tuple(float(p.get(k, 0.6)) for k in _GEN_KEYS)

        for group_key, idx in groupby(sorted(range(len(lines)), key=key), key=key):
            idx = list(idx)
            group = [lines[i] for i in idx]
            mode, language, gen = group_key[0], group_key[1], dict(zip(_GEN_KEYS, group_key[2:], strict=True))
            self._torch.manual_seed(seed_for(group[0]))
            try:
                wavs, sr = self._generate(mode, language, group, voices, gen)
            except self._torch.cuda.OutOfMemoryError as e:
                raise OutOfMemory(str(e)) from e
            finally:
                if self._device == "cuda":
                    self._torch.cuda.empty_cache()
            for i, w in zip(idx, wavs, strict=True):
                results[i] = Audio(np.asarray(w, dtype=np.float32), sr)
        return [results[i] for i in range(len(lines))]

    def _generate(self, mode: str, language: str, group: list[Line], voices: dict[str, Path], gen: dict):
        """One batched Qwen call."""
        texts = [spoken_text(ln) for ln in group]
        if mode == "design":
            return self._model("design").generate_voice_design(
                text=texts, language=language, instruct=[ln.params.get("instruct", "") for ln in group], **gen)
        if mode == "clone":
            m = self._model("clone")
            prompts = [self._clone_prompt(m, voices[ln.voice]) for ln in group]
            return m.generate_voice_clone(text=texts, language=[language] * len(group), voice_clone_prompt=prompts,
                                          **gen)
        raise ValueError(f"unknown qwen mode {mode!r}")

    def _clone_prompt(self, m, ref: Path):
        """Voice prompt from a reference file (x-vector only: no transcript needed), cached per file."""
        if ref not in self._prompts:
            from voicecrucible.core import audio
            y, sr = audio.decode(ref.read_bytes())
            self._prompts[ref] = m.create_voice_clone_prompt(ref_audio=(y, sr), x_vector_only_mode=True)[0]
        return self._prompts[ref]

    def unload(self) -> None:
        """Free models and GPU memory."""
        self._models.clear()
        self._prompts.clear()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()


ENGINE = QwenEngine
