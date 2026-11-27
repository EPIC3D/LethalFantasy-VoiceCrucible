"""Load and validate voicecrucible.toml.

The config file is the single place a user changes settings. Every value has a default, so an empty
file is valid. Unknown keys and wrong types are reported with the section and key name, never ignored.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the config file has an unknown key or a value of the wrong type."""


@dataclass
class PathsConfig:
    """Where Voice Crucible keeps its data. Relative paths are relative to the config file."""

    work_dir: str = "work"
    output_dir: str = "output"
    log_dir: str = "logs"


@dataclass
class CoordinatorConfig:
    """The machine that owns the job queue and serves the watcher."""

    port: int = 5130
    discovery_port: int = 5131
    watcher_port: int = 5132
    discovery: bool = True
    max_batch: int = 16


@dataclass
class WorkerConfig:
    """A GPU machine that renders jobs. Finds the coordinator by LAN beacon unless `coordinator` is set."""

    name: str = ""
    coordinator: str = ""
    max_batch: int = 16
    allow_update_requests: bool = False  # true = the paired coordinator may ask this worker to update itself
    seedvc_dir: str = "runtime/components/seed-vc"  # optional Seed-VC install (GPL-3.0), used by engine "qwen_vc"
    breeze_dir: str = "runtime/components/breeze"  # optional Breeze TTS 2 install (non-commercial weights)


@dataclass
class DirectorConfig:
    """Optional acting-direction step. mode: none | file | api."""

    mode: str = "none"
    file: str = ""
    api_base: str = "http://localhost:11434/v1"
    model: str = ""
    api_key_env: str = "VOICECRUCIBLE_API_KEY"
    context_length: int = 4096  # Ollama only: smaller = less VRAM; 0 = the server's default


@dataclass
class RenderConfig:
    """What to render and with which engine."""

    language: str = "en"
    engine: str = "chatterbox"
    characters: list[str] = field(default_factory=list)  # pack folders to render; empty = all characters
    profile: str = "lethalfantasy"  # profile name (profiles/<name>, installed separately) or a folder path


@dataclass
class ChecksConfig:
    """Defect filter applied by every worker (sent with each job, so all workers judge alike)."""

    enabled: list[str] = field(default_factory=lambda: ["words", "similarity", "quality", "pitch"])
    whisper_model: str = "small"
    min_text_match: float = 0.75
    min_similarity: float = 0.80
    min_mos: float = 2.0
    max_f0: float = 380.0
    max_attempts: int = 3
    # Strong emotions (strain while growing, shouting) sound far from the calm reference voice: user-checked good
    # takes scored similarity 0.63-0.77, MOS 1.7 and 546 Hz (2026-11-25). These lines get the looser limits below.
    intense_expressions: list[str] = field(default_factory=lambda: [
        "Hurt", "Angry", "Screaming", "Shocked", "Cry", "EmbarrasedMax"])
    intense_min_similarity: float = 0.63
    intense_min_mos: float = 1.5
    intense_max_f0: float = 600.0


@dataclass
class Config:
    """The whole configuration. `base_dir` is the folder relative paths are resolved against."""

    paths: PathsConfig = field(default_factory=PathsConfig)
    coordinator: CoordinatorConfig = field(default_factory=CoordinatorConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    director: DirectorConfig = field(default_factory=DirectorConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    checks: ChecksConfig = field(default_factory=ChecksConfig)
    base_dir: Path = field(default_factory=Path.cwd)
    source: Path | None = None  # the config file it was read from (passed on to commands the watcher starts)

    def path(self, value: str) -> Path:
        """Resolve a path from the config against the config file's folder."""
        p = Path(value)
        return p if p.is_absolute() else (self.base_dir / p).resolve()


_DIRECTOR_MODES = {"none", "file", "api"}


def _fill(section: Any, data: dict[str, Any], name: str) -> None:
    """Copy `data` into the dataclass `section`, checking key names and value types."""
    known = {f.name: f for f in fields(section)}
    for key, value in data.items():
        if key not in known:
            raise ConfigError(f"[{name}] unknown key '{key}'")
        current = getattr(section, key)
        ok = isinstance(value, type(current))
        if isinstance(current, float) and isinstance(value, int) and not isinstance(value, bool):
            value, ok = float(value), True
        if isinstance(current, int) and isinstance(value, bool) and not isinstance(current, bool):
            ok = False
        if not ok:
            raise ConfigError(f"[{name}] '{key}' must be {type(current).__name__}, got {type(value).__name__}")
        if isinstance(value, list) and not all(isinstance(v, str) for v in value):
            raise ConfigError(f"[{name}] '{key}' must be a list of strings")
        setattr(section, key, value)


def validate(cfg: Config) -> None:
    """Check value ranges and choices that types alone cannot express."""
    if cfg.director.mode not in _DIRECTOR_MODES:
        raise ConfigError(f"[director] mode must be one of {sorted(_DIRECTOR_MODES)}")
    if cfg.director.mode == "file" and not cfg.director.file:
        raise ConfigError("[director] mode = 'file' needs 'file' to be set")
    for name in ("output_dir", "work_dir"):
        if any(part.lower() == "bepinex" for part in cfg.path(getattr(cfg.paths, name)).parts):
            raise ConfigError(f"[paths] {name} must not be inside the game's BepInEx folder – Voice Crucible never writes "
                              f"into the game, so finished voices there cannot be overwritten by accident. Keep the "
                              f"default (output) and copy the voices folder into the game yourself.")
    c = cfg.coordinator
    for name, port in (("port", c.port), ("discovery_port", c.discovery_port), ("watcher_port", c.watcher_port)):
        if not 1024 <= port <= 65535:
            raise ConfigError(f"[coordinator] {name} must be between 1024 and 65535")
    if len({c.port, c.discovery_port, c.watcher_port}) != 3:
        raise ConfigError("[coordinator] port, discovery_port and watcher_port must be different")
    for name, value in (("coordinator", c.max_batch), ("worker", cfg.worker.max_batch)):
        if not 1 <= value <= 256:
            raise ConfigError(f"[{name}] max_batch must be between 1 and 256")
    k = cfg.checks
    if not 1 <= k.max_attempts <= 10:
        raise ConfigError("[checks] max_attempts must be between 1 and 10")
    for name, value in (("min_text_match", k.min_text_match), ("min_similarity", k.min_similarity),
                        ("intense_min_similarity", k.intense_min_similarity)):
        if not 0.0 <= value <= 1.0:
            raise ConfigError(f"[checks] {name} must be between 0 and 1")


def load(path: Path | None) -> Config:
    """Read a config file (or return defaults when `path` is None) and validate it."""
    cfg = Config()
    if path is None:
        validate(cfg)
        return cfg
    with open(path, "rb") as f:
        data = tomllib.load(f)
    cfg.base_dir = path.resolve().parent
    cfg.source = path.resolve()
    for name, value in data.items():
        section = getattr(cfg, name, None)
        if not is_dataclass(section) or not isinstance(value, dict):
            raise ConfigError(f"unknown section [{name}]")
        _fill(section, value, name)
    validate(cfg)
    return cfg
