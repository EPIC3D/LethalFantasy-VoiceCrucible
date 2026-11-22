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
        "leftover": state.leftover if state.leftover and remaining else None,
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
                            "files": sum(1 for f in sub.iterdir() if f.suffix in (".ogg", ".wav") and ".bak." not in f.name
                                            and ".skipped." not in f.name)})
    value = {"pack": str(pack), "language": state.language, "profile": state.profile, "folders": folders,
             "report": str(state.output_root / "report.tsv"), "logs": str(state.log_dir) if state.log_dir else ""}
    _output_cache.update(at=time.time(), value=value)
    return value


def _skip(state: CoordinatorState, uid) -> tuple[int, dict]:
    """Leave a problem line without a voice; an exported take is renamed to <name>.skipped.<ext> (the plugin does not
    play it, nothing is deleted)."""
    if type(uid) is not int:
        return 400, {"error": "no line"}
    done = state.queue.skip(uid)
    if done is None:
        return 404, {"error": "this line cannot be skipped (it is rendering right now)"}
    line, output = done
    if output:
        path = (state.output_root / output).resolve()
        if path.is_relative_to(state.output_root.resolve()) and path.is_file():
            path.replace(path.with_name(f"{path.stem}.skipped{path.suffix}"))
    sound = skip_sound(getattr(state, "profile", ""))
    if sound is not None:  # the user's own "nothing here" sound (e.g. crickets) instead of silence
        from voicecrucible.coordinator import results
        from voicecrucible.core import audio
        y, sr = audio.decode(sound.read_bytes())
        path = results.save(state.output_root, state.language, line, "ogg", audio.encode(y, sr, "ogg"))
        state.queue.mark_spoken(uid, path.relative_to(state.output_root).as_posix())
        _log.info("%s skipped in the watcher – %s plays instead", line.file_stem, sound.name)
        return 200, {"skipped": line.file_stem, "sound": sound.name}
    _log.info("%s skipped in the watcher – left without a voice", line.file_stem)
    return 200, {"skipped": line.file_stem}


def skip_sound(profile: str) -> Path | None:
    """The profile's optional voices/skip_sound.* – played for skipped lines instead of silence (off without it)."""
    from voicecrucible.installer import layout
    if not profile:
        return None
    folder = (Path(profile) if ("/" in profile or "\\" in profile) else layout.ROOT / "profiles" / profile) / "voices"
    for ext in ("wav", "ogg", "flac", "mp3"):
        if (folder / f"skip_sound.{ext}").is_file():
            return folder / f"skip_sound.{ext}"
    return None


def _accept(state: CoordinatorState, uid) -> tuple[int, dict]:
    """Accept a problem line by hand: its take becomes the line's voice file (exported if it was not yet)."""
    from voicecrucible.coordinator import app
    if type(uid) is not int:
        return 400, {"error": "no line"}
    output, _take = state.queue.problem_audio(uid)
    line = state.queue.accept(uid)
    if line is None:
        return 404, {"error": "this line cannot be accepted (no take, or it is rendering right now)"}
    if not output:  # waiting for a retry: its best take so far was not exported yet
        app._export_best_take(state, line, accepted=True)
    _log.info("%s accepted by hand in the watcher", line.file_stem)
    return 200, {"accepted": line.file_stem}


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
        self.default_output = cfg.path(cfg.paths.output_dir)
        self.output_dir = self.default_output

    def restore_output(self, state: CoordinatorState) -> None:
        """Use the voice pack folder last chosen in the watcher (if it is still allowed)."""
        from voicecrucible.watcher import tasks
        saved = self.memory.load().get("output")
        if saved and Path(saved) != self.default_output:
            try:
                self.output_dir = tasks.check_output_folder(self.cfg, saved)
                state.output_root = self.output_dir
            except tasks.TaskError as e:
                _log.warning("the voice pack folder chosen in the watcher is not used: %s", e)

    def select_output(self, folder: str, state: CoordinatorState) -> Path:
        """Switch the voice pack folder – only while nothing is waiting or rendering."""
        from voicecrucible.watcher import tasks
        counts = state.queue.counts()
        if counts["pending"] + counts["leased"]:
            raise tasks.TaskError("lines are still waiting or rendering – let the render finish (or cancel it) "
                                  "before you change the voice pack folder")
        self.output_dir = tasks.check_output_folder(self.cfg, folder)
        state.output_root = self.output_dir
        self.memory.save({"output": str(self.output_dir)})
        _log.info("voice pack folder set in the watcher: %s", self.output_dir)
        return self.output_dir

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
                "default_profile": self.default_folder.name, "output_dir": str(self.output_dir),
                "default_output": str(self.default_output), "profiles": tasks.profiles_overview(self.root),
                "voices": voices, "voices_error": voices_error, "setup_needed": self._setup_needed(),
                "skip_sound": (s.name if (s := skip_sound(str(self.profile_folder))) else ""),
                "names": self._respellings()}

    def _respellings(self) -> dict[str, str]:
        """Respelling -> written name of the active profile, so the page shows lines with their real names."""
        import json
        try:
            data = json.loads((self.profile_folder / "pronunciation.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {s: name for name, spellings in data.items() if not name.startswith("_") and isinstance(spellings, list)
                for s in spellings if isinstance(s, str)}

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
            args = tasks.build_args(form, sorted(engines.available()), self.profile_folder.name,
                                    str(self.output_dir) if self.output_dir != self.default_output else "")
            if form.get("action") in ("render", "dry-run", "story", "story-join"):
                self.memory.save({k: v for k, v in form.items() if k not in ("profile", "output")})
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
        if path == "/api/output-select":
            folder = str(body.get("folder", "")) or str(self.default_output)
            return {"output": str(self.select_output(folder, state))}
        if path == "/api/export-info":
            return tasks.export_info(str(body.get("lines", "")))
        if path == "/api/diagnose":
            return {"report": tasks.diagnose_report(self.cfg)}
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
    # read once: the page always matches the running program, also when an update replaced the file on disk
    page = _PAGE.read_bytes()

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
                self._send(200, page, "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json(200, status(state))
            elif self.path == "/api/control" and controls is not None:
                self._json(200, controls.status())
            elif self.path.startswith("/api/problem-audio?"):
                self._problem_audio()
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
            elif self.path == "/api/skip":
                self._json(*_skip(state, self._body().get("uid")))
            elif self.path == "/api/accept":
                self._json(*_accept(state, self._body().get("uid")))
            elif self.path == "/api/cancel-render":
                n = state.queue.cancel()
                state.leftover = None
                _log.info("render cancelled in the watcher: %d waiting/rendering line(s) removed", n)
                self._json(200, {"removed": n})
            elif self.path == "/api/pause":
                state.registry.paused = self._body().get("paused") is True
                if not state.registry.paused:
                    state.leftover = None  # resumed: the earlier render goes on
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
                                                         "/api/profile-import", "/api/profile-open", "/api/run-setup",
                                                         "/api/diagnose", "/api/output-select",
                                                         "/api/export-info"):
                from voicecrucible.watcher.tasks import TaskError
                try:
                    self._json(200, controls.action(self.path, self._body(), state))
                except TaskError as e:
                    self._json(400, {"error": str(e)})
            else:
                self._json(404, {"error": "not found"})

        def _problem_audio(self) -> None:
            """Play the take of a problem line: the exported best take, else the best failed take so far. Only
            files inside the coordinator's own output / takes folders are served."""
            from urllib.parse import parse_qs, urlparse
            try:
                uid = int(parse_qs(urlparse(self.path).query).get("uid", ["-1"])[0])
            except ValueError:
                uid = -1
            output, take = state.queue.problem_audio(uid)
            candidates = [(state.output_root / output, state.output_root)] if output else []
            if take:
                candidates.append((Path(take), state.takes_dir))
            for path, root in candidates:
                try:
                    path = path.resolve()
                    if path.is_relative_to(root.resolve()) and path.is_file():
                        kind = "audio/ogg" if path.suffix == ".ogg" else "audio/wav"
                        self._send(200, path.read_bytes(), kind)
                        return
                except OSError:
                    pass
            self._json(404, {"error": "no audio for this line"})

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
