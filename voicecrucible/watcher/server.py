"""Local-only HTTP server for the watcher page (bound to 127.0.0.1, never reachable from the network).

Actions (new pairing code, revoke a worker) require a custom header, which a foreign web page cannot send
to localhost without a CORS preflight that this server never approves. Requests with a foreign Host header
are refused (DNS rebinding).
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from voicecrucible import __version__
from voicecrucible.coordinator.app import CoordinatorState
from voicecrucible.core import log, protocol

_log = log.get(__name__)
_PAGE = Path(__file__).with_name("index.html")
ACTION_HEADER = "X-Voice-Crucible"


def _compare(version: str) -> str:
    """'older' / 'newer' / 'same' compared with this coordinator ('' when unknown)."""
    from voicecrucible.installer.update import UpdateError, _version_tuple
    if not version:
        return ""
    try:
        mine, theirs = _version_tuple(__version__), _version_tuple(version)
    except UpdateError:
        return ""
    return "same" if theirs == mine else "older" if theirs < mine else "newer"


def status(state: CoordinatorState) -> dict:
    """Everything the watcher page shows, as one JSON object."""
    counts = state.queue.counts()
    workers = state.registry.snapshot()
    paired = state.pairing.paired()
    for wid, info in paired.items():
        if not any(w["worker_id"] == wid for w in workers):
            workers.append({"worker_id": wid, "name": info["name"], "online": False, "gpus": [], "done": 0,
                            "failed": 0, "busy_lines": 0, "lines_per_min": 0, "address": "", "version": "",
                            "accepts_updates": False, "update_status": "", "mode": "run"})
    for w in workers:
        w["version_state"] = _compare(w.get("version", ""))
    speed = sum(w["lines_per_min"] for w in workers if w["online"])
    remaining = counts["pending"] + counts["leased"]
    elapsed = _run_clock(state, remaining)
    code = state.pairing.current_code()
    return {
        "coordinator_id": state.identity.coordinator_id,
        "version": __version__,
        "paused": state.registry.paused,
        "paired": [{"worker_id": wid, "name": info["name"]} for wid, info in paired.items()],
        "fingerprint": protocol.short_fingerprint(state.identity.fingerprint),
        "counts": counts,
        "eta_seconds": round(remaining / speed * 60) if speed > 0 and remaining else None,
        "elapsed_seconds": elapsed, "lines_per_min": round(speed, 1),
        "workers": workers,
        "problems": state.queue.recent_problems(),
        "pairing_code": None if code is None else {"code": code[0], "seconds_left": round(code[1] - time.time())},
        "output": _output(state),
    }


def _run_clock(state: CoordinatorState, remaining: int) -> int | None:
    """Seconds since the current render began (from the queue file, so a coordinator restart keeps it)."""
    start, end = state.queue.run_times()
    return None if start is None else round((end or time.time()) - start)


_output_cache: dict = {"at": 0.0, "value": None}


def _output(state: CoordinatorState) -> dict:
    """Where the finished files go: pack folder, files per character folder, report and logs (cached 10 s)."""
    if _output_cache["value"] is not None and time.time() - _output_cache["at"] < 10:
        return _output_cache["value"]
    pack = state.output_root / "voices" / state.language
    folders = []
    if pack.exists():
        for sub in sorted(p for p in pack.iterdir() if p.is_dir()):
            folders.append({"folder": sub.name, "path": str(sub),
                            "files": sum(1 for f in sub.iterdir() if f.suffix in (".ogg", ".wav") and ".bak." not in f.name)})
    value = {"pack": str(pack), "language": state.language, "profile": state.profile, "folders": folders,
             "report": str(state.output_root / "report.tsv"), "logs": str(state.log_dir) if state.log_dir else ""}
    _output_cache.update(at=time.time(), value=value)
    return value


def is_local_host(host: str | None, port: int) -> bool:
    """True when the Host header names this machine (refuses DNS rebinding: a foreign domain pointed at 127.0.0.1)."""
    return (host or "").lower() in (f"127.0.0.1:{port}", f"localhost:{port}")


class Controls:
    """What the watcher can start on this computer (None in tests and without a config)."""

    def __init__(self, cfg, api_port: int, profile_folder: Path, root: Path | None = None):
        from voicecrucible.installer import layout
        from voicecrucible.watcher import tasks
        self.cfg, self.api_port = cfg, api_port
        self.root = root or layout.ROOT
        self.tasks = tasks.TaskRunner(cfg)
        self.worker = tasks.LocalWorker(cfg)
        self.memory = tasks.FormMemory(cfg)
        self.default_folder = profile_folder
        chosen = self.memory.load().get("profile")
        self.profile_folder = self._folder(chosen) if chosen and self._folder(chosen).is_dir() else profile_folder

    def _folder(self, name: str) -> Path:
        from voicecrucible.installer import profiles
        return profiles.profiles_dir(self.root) / name

    def _installed(self, name: str) -> Path:
        """Folder of an installed profile by name (refuses anything else, e.g. paths)."""
        from voicecrucible.watcher import tasks
        names = {p["name"] for p in tasks.profiles_overview(self.root)}
        if name not in names:
            raise tasks.TaskError(f"no installed profile named {name!r}")
        return self._folder(name)

    def select(self, name: str, state: CoordinatorState) -> None:
        """Make another profile active for the watcher's commands and the coordinator's checks (names)."""
        import copy

        from voicecrucible.coordinator import run
        folder = self._installed(name)
        cfg = copy.deepcopy(self.cfg)
        cfg.render.profile = name
        state.check_settings = run.check_settings(cfg)
        state.profile = name
        self.profile_folder = folder
        self.memory.save({"profile": name})
        _log.info("profile '%s' selected in the watcher", name)

    def status(self) -> dict:
        from voicecrucible.engines import base as engines
        from voicecrucible.watcher import tasks
        try:
            voices, voices_error = tasks.voices(self.profile_folder), ""
        except Exception as e:  # noqa: BLE001 - a broken profile is shown on the page, not a crash
            voices, voices_error = [], str(e)
        return {"task": self.tasks.status(), "local_worker": self.worker.status(), "form": self.memory.load(),
                "engines": sorted(engines.available()), "default_engine": self.cfg.render.engine,
                "profile": self.profile_folder.name, "bundled": self.profile_folder.name in tasks.BUNDLED_PROFILES,
                "default_profile": self.default_folder.name, "profiles": tasks.profiles_overview(self.root),
                "voices": voices, "voices_error": voices_error, "setup_needed": self._setup_needed()}

    def _setup_needed(self) -> str:
        from voicecrucible.installer import setupstate
        return setupstate.needed(self.root)

    def action(self, path: str, body: dict, state: CoordinatorState) -> dict:
        """Run one control action; TaskError -> shown on the page."""
        from voicecrucible.engines import base as engines
        from voicecrucible.installer import profiles
        from voicecrucible.watcher import tasks
        if path == "/api/task":
            form = body.get("form") if isinstance(body.get("form"), dict) else {}
            args = tasks.build_args(form, sorted(engines.available()), self.profile_folder.name)
            if form.get("action") in ("render", "dry-run", "story", "story-join"):
                self.memory.save({k: v for k, v in form.items() if k != "profile"})
            self.tasks.start(args)
            return {"started": " ".join(args)}
        if path == "/api/pick":
            return {"path": tasks.pick(str(body.get("kind", "")), str(body.get("title", "Choose")),
                                       str(body.get("start", "")))}
        if path == "/api/local-worker":
            if not self.worker.paired():
                self.worker.pair(state.pairing.new_code(), self.api_port)
            self.worker.start()
            return {"ok": True}
        if path == "/api/voice-replace":
            target = tasks.replace_voice(self.profile_folder, str(body.get("character", "")),
                                         str(body.get("engine", "")), str(body.get("file", "")))
            return {"file": str(target)}
        if path == "/api/profile-select":
            self.select(str(body.get("name", "")), state)
            return {"profile": state.profile}
        if path == "/api/profile-new":
            source = str(body.get("source", ""))
            self._installed(source)
            try:
                target = profiles.new_profile(str(body.get("name", "")), self.root, source=source)
            except profiles.ProfileError as e:
                raise tasks.TaskError(str(e)) from None
            _log.info("profile '%s' created from '%s' in the watcher", target.name, source)
            self.select(target.name, state)
            return {"profile": target.name}
        if path == "/api/profile-import":
            pack = Path(str(body.get("file", "")))
            if pack.suffix.lower() != ".zip" or not pack.is_file():
                raise tasks.TaskError("choose a profile pack (.zip)")
            try:
                meta, backup = profiles.install(pack, self.root)
            except (profiles.ProfileError, ValueError, OSError) as e:
                raise tasks.TaskError(f"profile not installed: {e}") from None
            except Exception as e:  # noqa: BLE001 - e.g. a broken zip file
                raise tasks.TaskError(f"profile not installed: {e}") from None
            _log.info("profile '%s' imported in the watcher", meta["name"])
            return {"profile": meta["name"], "backup": str(backup) if backup else ""}
        if path == "/api/run-setup":
            import threading
            if self.tasks.status()["running"]:
                raise tasks.TaskError("a task is still running – wait until it finishes")
            threading.Thread(target=tasks.run_setup, args=(self.cfg, state.registry, self.worker, state.stop_event.set),
                             daemon=True).start()
            return {"ok": True}
        if path == "/api/profile-open":
            tasks.open_folder(self._installed(str(body.get("name", ""))))
            return {"ok": True}
        raise tasks.TaskError("unknown action")


def make_server(state: CoordinatorState, port: int, controls: Controls | None = None) -> ThreadingHTTPServer:
    """Create the watcher server on 127.0.0.1 (not started)."""

    class Handler(BaseHTTPRequestHandler):
        """Serves the page, its status JSON and two actions."""

        server_version = "VoiceCrucible"
        sys_version = ""

        def _local_host(self) -> bool:
            """Refuse requests whose Host is not this machine (DNS rebinding: a foreign domain pointed at 127.0.0.1)."""
            if is_local_host(self.headers.get("Host"), port):
                return True
            self._json(403, {"error": "open the watcher as http://127.0.0.1:%d/" % port})
            return False

        def do_GET(self) -> None:  # noqa: N802
            if not self._local_host():
                return
            if self.path in ("/", "/index.html"):
                self._send(200, _PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json(200, status(state))
            elif self.path == "/api/control" and controls is not None:
                self._json(200, controls.status())
            elif self.path.startswith("/api/voice?") and controls is not None:
                self._voice()
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._local_host():
                return
            if self.headers.get(ACTION_HEADER) != "1":
                self._json(403, {"error": "missing action header"})
                return
            if self.path == "/api/pairing-code":
                code = state.pairing.new_code()
                _log.info("new pairing code created in the watcher")
                self._json(200, {"code": code})
            elif self.path == "/api/request-update":
                names = state.registry.request_update()
                _log.info("update requested in the watcher for: %s", ", ".join(names) or "nobody")
                self._json(200, {"workers": names})
            elif self.path == "/api/pause":
                state.registry.paused = self._body().get("paused") is True
                _log.info("rendering %s in the watcher", "paused" if state.registry.paused else "resumed")
                self._json(200, {"paused": state.registry.paused})
            elif self.path == "/api/worker":
                body = self._body()
                try:
                    ok = state.registry.set_mode(str(body.get("worker_id", "")), str(body.get("mode", "")))
                except ValueError:
                    ok = False
                if ok:
                    _log.info("worker %s set to '%s' in the watcher", body.get("worker_id"), body.get("mode"))
                self._json(200 if ok else 404, {"ok": ok})
            elif self.path == "/api/revoke":
                worker_id = self._body().get("worker_id", "")
                ok = isinstance(worker_id, str) and state.pairing.revoke(worker_id)
                if ok:
                    state.registry.forget(worker_id)
                    _log.info("worker %s revoked in the watcher", worker_id)
                self._json(200 if ok else 404, {"revoked": ok})
            elif controls is not None and self.path in ("/api/task", "/api/pick", "/api/local-worker", "/api/voice-replace",
                                                         "/api/profile-select", "/api/profile-new",
                                                         "/api/profile-import", "/api/profile-open", "/api/run-setup"):
                from voicecrucible.watcher.tasks import TaskError
                try:
                    self._json(200, controls.action(self.path, self._body(), state))
                except TaskError as e:
                    self._json(400, {"error": str(e)})
            else:
                self._json(404, {"error": "not found"})

        def _voice(self) -> None:
            """Play a reference clip of the active profile (the path comes from the profile, not from the page)."""
            from urllib.parse import parse_qs, urlparse

            from voicecrucible.watcher.tasks import TaskError, voice_path
            q = parse_qs(urlparse(self.path).query)
            try:
                path = voice_path(controls.profile_folder, q.get("character", [""])[0], q.get("engine", [""])[0])
                self._send(200, path.read_bytes(), "audio/wav")
            except (TaskError, OSError):
                self._json(404, {"error": "no such voice"})

        def _body(self) -> dict:
            """Small JSON body of an action (at most 4 KB); {} when missing or invalid."""
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 4096)
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _send(self, code: int, data: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args) -> None:
            pass  # the page polls every few seconds; keep the log clean

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
