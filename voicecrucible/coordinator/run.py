"""`crucible coordinator`: start the API, discovery and watcher, print the pairing code, run until Ctrl+C."""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

from voicecrucible.checks import base as checks_base
from voicecrucible.coordinator import app, discovery, tls
from voicecrucible.coordinator.assets import AssetStore
from voicecrucible.coordinator.pairing import Pairing
from voicecrucible.coordinator.scheduler import WorkerRegistry
from voicecrucible.core import languages, log, protocol
from voicecrucible.core.config import Config, ConfigError
from voicecrucible.textprep.pronounce import Lexicon
from voicecrucible.core.queue import JobQueue
from voicecrucible.watcher import server as watcher_server

_log = log.get(__name__)


def check_settings(cfg: Config) -> dict:
    """Check settings sent with every job: thresholds from [checks], names from the profile's lexicon."""
    unknown = set(cfg.checks.enabled) - set(checks_base.available())
    if unknown:
        raise ConfigError(f"[checks] unknown check(s) {sorted(unknown)} (known: {checks_base.available()})")
    settings = {k: v for k, v in asdict(cfg.checks).items() if k != "max_attempts"}
    settings["language"] = languages.whisper_code(cfg.render.language)
    lexicon_file = profile_dir(cfg) / "pronunciation.json"
    if lexicon_file.exists():
        lexicon = Lexicon.load(lexicon_file)
        settings["names"] = lexicon.respellings()
        settings["whisper_prompt"] = ", ".join(lexicon.names()) + "."
    return settings


def profile_dir(cfg: Config) -> Path:
    """Folder of the active profile: a name means profiles/<name>, anything with a slash is a path."""
    value = cfg.render.profile
    if "/" in value or "\\" in value:
        return cfg.path(value)
    return Path(__file__).parents[2] / "profiles" / value


def build_state(cfg: Config) -> app.CoordinatorState:
    """Create (or load) the coordinator identity, queue, pairing data and assets from the config."""
    folder = cfg.path(cfg.paths.work_dir) / "coordinator"
    identity = tls.ensure_identity(folder)
    return app.CoordinatorState(
        identity=identity,
        queue=JobQueue(folder / "queue.sqlite", max_attempts=cfg.checks.max_attempts),
        pairing=Pairing(folder / "workers.json", identity.fingerprint),
        registry=WorkerRegistry(cfg.coordinator.max_batch),
        output_root=cfg.path(cfg.paths.output_dir),
        language=cfg.render.language,
        assets=AssetStore(folder / "assets"),
        check_settings=check_settings(cfg),
    )


class RunningCoordinator:
    """The started servers; `stop()` shuts everything down cleanly."""

    def __init__(self, state: app.CoordinatorState, api_port: int, watcher_port: int, discovery_port: int | None):
        self.state = state
        self.api = app.make_server(state, "0.0.0.0", api_port)
        self.watcher = watcher_server.make_server(state, watcher_port)
        self.api_port = self.api.server_address[1]
        self.watcher_port = self.watcher.server_address[1]
        self.discovery = None
        if discovery_port is not None:
            self.discovery = discovery.DiscoveryResponder(discovery_port, state.identity.coordinator_id,
                                                          self.api_port, state.identity.fingerprint)
        self._threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (self.api, self.watcher)]

    def start(self) -> None:
        """Start all servers in background threads."""
        for t in self._threads:
            t.start()
        if self.discovery is not None:
            self.discovery.start()

    def stop(self) -> None:
        """Stop all servers and close the queue."""
        for s in (self.api, self.watcher):
            s.shutdown()
            s.server_close()
        if self.discovery is not None:
            self.discovery.stop()
        self.state.queue.close()


def run(cfg: Config) -> int:
    """Run the coordinator in the foreground until Ctrl+C."""
    state = build_state(cfg)
    c = cfg.coordinator
    try:
        running = RunningCoordinator(state, c.port, c.watcher_port, c.discovery_port if c.discovery else None)
    except OSError as e:
        _log.error("cannot open the coordinator ports (%s) – is another coordinator already running?", e)
        return 1
    running.start()
    code = state.pairing.new_code()
    _log.info("coordinator %s running, certificate %s", state.identity.coordinator_id,
              protocol.short_fingerprint(state.identity.fingerprint))
    _log.info("watcher: http://127.0.0.1:%d  (only on this computer)", running.watcher_port)
    _log.info("pairing code for new workers: %s  (valid 10 minutes, new code in the watcher)", code)
    _log.info("press Ctrl+C to stop")
    stop = threading.Event()
    try:
        while not stop.wait(30):
            if n := state.queue.expire():
                _log.warning("%d line(s) of a lost worker went back to the queue", n)
    except KeyboardInterrupt:
        _log.info("stopping…")
    finally:
        running.stop()
    return 0
