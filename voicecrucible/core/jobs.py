"""Data classes passed between the packages: a line to speak, a render job, a take and check results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Line:
    """One spoken line: translation key, speaker folder, speakable text and acting hints."""

    key: str
    character: str
    text: str
    emotion: str = ""
    direction: str = ""
    variant: str = ""  # "", "he", "she" or "they"
    uid: int = 0  # queue row id, set by the job queue
    voice: str = ""  # SHA-256 of the reference voice file (an asset the worker fetches and caches)
    params: dict = field(default_factory=dict)  # engine settings resolved before queueing (e.g. exaggeration)
    attempt: int = 1  # 1 = first take; also changes the random seed of retries

    @property
    def file_stem(self) -> str:
        """File name without extension, as the plugin looks it up: KEY or KEY__variant."""
        return f"{self.key}__{self.variant}" if self.variant else self.key

    @property
    def label(self) -> str:
        """For logs: the line ID the watcher shows and the file name, e.g. "#1234 KEY__they"."""
        return f"#{self.uid} {self.file_stem}"


@dataclass
class CheckResult:
    """Outcome of one defect check on one take."""

    check: str
    passed: bool
    reason: str = ""
    score: float | None = None


@dataclass
class Job:
    """A batch of lines handed to one worker. `settings` = the coordinator's check settings for this job."""

    job_id: str
    engine: str
    lines: list[Line]
    attempt: int = 1
    settings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Plain dict for sending the job as JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        """Rebuild a job received as JSON."""
        return cls(job_id=data["job_id"], engine=data["engine"], lines=[Line(**ln) for ln in data["lines"]],
                   attempt=data.get("attempt", 1), settings=data.get("settings") or {})
