"""Render a job: fetch reference voices, run the engine, check every take, encode the passed ones.

The batch size is halved when the GPU runs out of memory. Failed takes go back with their reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from voicecrucible.checks.base import Candidate, CheckSet, summary
from voicecrucible.core import audio, log
from voicecrucible.core.jobs import Job
from voicecrucible.engines import base

_log = log.get(__name__)


@dataclass
class TakeResult:
    """Outcome of one line: encoded audio when passed, a reason when not."""

    uid: int
    passed: bool
    reason: str = ""
    ext: str = ""
    audio: bytes = b""


class Runner:
    """Keeps one engine and one check set loaded and renders jobs with them."""

    def __init__(self, device: str, max_batch: int = 16, voice_path: Callable[[str], Path] | None = None,
                 output_format: str = "ogg"):
        self.device = device
        self.batch_size = max(1, max_batch)
        self.voice_path = voice_path
        self.output_format = output_format
        self._engine: base.Engine | None = None
        self._checks = CheckSet(device)

    def render(self, job: Job) -> list[TakeResult]:
        """Render and check every line of the job."""
        engine = self._engine_for(job.engine)
        self._checks.configure(job.settings)
        voices = {ln.voice: self._voice(ln.voice) for ln in job.lines if ln.voice}
        results: list[TakeResult] = []
        i = 0
        while i < len(job.lines):
            chunk = job.lines[i:i + self.batch_size]
            try:
                audios = engine.render(chunk, voices)
            except base.OutOfMemory:
                if self.batch_size == 1:
                    raise
                self.batch_size = max(1, self.batch_size // 2)
                _log.warning("GPU out of memory – batch size lowered to %d", self.batch_size)
                continue
            if len(audios) != len(chunk):
                raise RuntimeError(f"engine '{engine.name}' returned {len(audios)} results for {len(chunk)} lines")
            for line, a in zip(chunk, audios, strict=True):
                y = audio.pad_lead_in(a.samples, a.sample_rate)
                take = Candidate(line, y, a.sample_rate, voices.get(line.voice))
                passed, reason = summary(self._checks.run(take))
                if passed:
                    results.append(TakeResult(line.uid, True, ext=self.output_format,
                                              audio=audio.encode(y, a.sample_rate, self.output_format)))
                else:
                    _log.info("%s take %d rejected: %s", line.file_stem, line.attempt, reason)
                    results.append(TakeResult(line.uid, False, reason=reason))
            i += len(chunk)
        return results

    def close(self) -> None:
        """Unload the current engine."""
        if self._engine is not None:
            self._engine.unload()
            self._engine = None

    def _voice(self, sha: str) -> Path:
        """Local path of a reference voice."""
        if self.voice_path is None:
            raise RuntimeError("this job needs reference voices, but the runner has no asset source")
        return self.voice_path(sha)

    def _engine_for(self, name: str) -> base.Engine:
        """The loaded engine `name`, switching engines when the job needs a different one."""
        if self._engine is None or self._engine.name != name:
            self.close()
            _log.info("loading engine '%s' on %s", name, self.device)
            engine = base.create(name)
            engine.load(self.device)
            self._engine = engine
        return self._engine
