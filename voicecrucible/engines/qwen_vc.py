"""Acting pipeline (v4): Qwen3 VoiceDesign acts the line from its direction, Seed-VC converts the result to
the character's fixed reference voice. User verdict: consistent voice, good acting.

Line params: everything of the qwen engine (mode "design", instruct, temperatures) + vc_steps (50).
"""

from __future__ import annotations

from pathlib import Path

from voicecrucible.core.jobs import Line
from voicecrucible.engines.base import Audio, Engine
from voicecrucible.engines.qwen import QwenEngine
from voicecrucible.engines.seedvc import SeedVC


class QwenVCEngine(Engine):
    """Qwen VoiceDesign followed by Seed-VC voice conversion to the line's reference voice."""

    name = "qwen_vc"

    def __init__(self) -> None:
        self._qwen = QwenEngine()
        self._vc: SeedVC | None = None

    def load(self, device: str) -> None:
        """Start Seed-VC first (fails fast when the optional component is missing), then Qwen."""
        self._vc = SeedVC()
        self._qwen.load(device)

    def render(self, lines: list[Line], voices: dict[str, Path]) -> list[Audio]:
        """Act all lines with Qwen (batched), then convert each one to its reference voice."""
        acted = self._qwen.render(lines, voices)
        out = []
        for line, a in zip(lines, acted, strict=True):
            y, sr = self._vc.convert(a.samples, a.sample_rate, voices[line.voice],
                                     int(line.params.get("vc_steps", 50)))
            out.append(Audio(y, sr))
        return out

    def unload(self) -> None:
        """Stop Seed-VC and free Qwen."""
        self._qwen.unload()
        if self._vc is not None:
            self._vc.close()
            self._vc = None


ENGINE = QwenVCEngine
