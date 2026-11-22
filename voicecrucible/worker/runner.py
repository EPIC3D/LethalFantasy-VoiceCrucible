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
    """Outcome of one line: encoded audio (also for a failed take – kept as a fallback), reason, quality score."""

    uid: int
    passed: bool
    reason: str = ""
    ext: str = ""
    audio: bytes = b""
    score: float = -1.0  # audio quality (MOS) of the take, used to pick the best take if every attempt fails


def models_folder() -> Path:
    """Where downloaded models are kept (runtime/models, see installer.layout)."""
    import os
    hf = os.environ.get("HF_HOME")
    return Path(hf).parent if hf else Path.home() / ".cache"


def _folder_bytes(folder: Path) -> int:
    """Total size of the files below `folder` (0 when it does not exist)."""
    total = 0
    try:
        for f in folder.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


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
        self.progress: dict = {}  # current job: id, engine, lines, done, current line – shown in the watcher

    def progress_snapshot(self) -> dict:
        """The progress for the heartbeat; while a model loads, also the size of the model folder (it grows while
        a model is downloaded the first time, so the watcher can show that the worker is not stuck)."""
        snap = dict(self.progress)
        if snap.get("phase") == "loading":
            snap["models_gb"] = round(_folder_bytes(models_folder()) / 1e9, 2)
        return snap

    def render(self, job: Job, cancel: Callable[[], bool] | None = None) -> list[TakeResult]:
        """Render and check the lines of the job; stops early (between chunks) when `cancel()` turns True –
        the results so far are returned, the caller gives the rest of the job back."""
        self.progress = {"id": job.job_id[:8], "engine": job.engine, "lines": len(job.lines), "done": 0,
                         "current": job.lines[0].file_stem if job.lines else "", "phase": "loading"}
        engine = self._engine_for(job.engine)
        self._checks.configure(job.settings)
        self.progress["phase"] = "rendering"
        voices = {ln.voice: self._voice(ln.voice) for ln in job.lines if ln.voice}
        results: list[TakeResult] = []
        i = 0
        while i < len(job.lines):
            self.progress.update(done=i, current=job.lines[i].file_stem)
            if cancel is not None and cancel():
                _log.info("job %s stopped after %d of %d line(s)", job.job_id[:8], i, len(job.lines))
                break
            size = min(self.batch_size, engine.batch_lines or self.batch_size)
            chunk = job.lines[i:i + size]
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
                checks = self._checks.run(take)
                passed, reason = summary(checks)
                score = next((c.score for c in checks if c.check == "quality" and c.score is not None), 0.0)
                if not passed:
                    _log.info("%s take %d rejected: %s", line.file_stem, line.attempt, reason)
                results.append(TakeResult(line.uid, passed, reason=reason, ext=self.output_format, score=score,
                                          audio=audio.encode(y, a.sample_rate, self.output_format)))
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
