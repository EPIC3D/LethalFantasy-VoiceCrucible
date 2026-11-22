"""What the watcher can start on this computer: crucible commands, the local worker and file pickers.

Every action runs the same `crucible` command as the command line (same checks, same log), in a child
process. Only a fixed set of commands and form fields is accepted – the page never sends a command line.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from voicecrucible.core import config as config_mod
from voicecrucible.core import log

_log = log.get(__name__)
ROOT = Path(__file__).resolve().parents[2]
_PREFIX = re.compile(r"^[A-Za-z0-9_]{0,120}$")
_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class TaskError(ValueError):
    """A form value the watcher refuses (shown on the page)."""


def _base(cfg: config_mod.Config) -> list[str]:
    """`python -m voicecrucible.cli [-c <config>]` – the same program and settings as this coordinator."""
    cmd = [sys.executable, "-m", "voicecrucible.cli"]
    if cfg.source is not None:
        cmd += ["-c", str(cfg.source)]
    return cmd


def _folder(value, name: str, required: bool = True) -> str | None:
    if not value:
        if required:
            raise TaskError(f"choose the {name}")
        return None
    p = Path(str(value))
    if not p.is_dir():
        raise TaskError(f"{name} not found: {p}")
    return str(p.resolve())


def _file(value, name: str) -> str | None:
    if not value:
        return None
    p = Path(str(value))
    if not p.is_file():
        raise TaskError(f"{name} not found: {p}")
    return str(p.resolve())


def build_args(form: dict, engines: list[str], profile: str = "", output: str = "") -> list[str]:
    """Turn the page's form into crucible arguments (only known fields, each checked); `profile` = active profile,
    `output` = active voice pack folder."""
    args = _build_args(form, engines)
    if profile and args[0] in ("render", "story", "recheck") and "--retry-failed" not in args:
        args += ["--profile", profile]
    if output and (args[0] in ("render", "story", "report", "recheck")) and "--retry-failed" not in args:
        args += ["--output", output]
    return args


def check_output_folder(cfg: config_mod.Config, folder: str) -> Path:
    """A voice pack folder chosen in the watcher: absolute, creatable, never inside the game's BepInEx folder."""
    import copy
    if not folder:
        raise TaskError("choose a folder for the voice pack")
    p = Path(folder).resolve()
    test = copy.deepcopy(cfg)
    test.paths.output_dir = str(p)
    try:
        config_mod.validate(test)
    except config_mod.ConfigError as e:
        raise TaskError(str(e)) from None
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise TaskError(f"cannot use this folder: {e}") from None
    return p


def _build_args(form: dict, engines: list[str]) -> list[str]:
    action = form.get("action")
    if action == "retry-failed":
        return ["render", "--retry-failed"]
    if action == "report":
        return ["report"]
    if action == "recheck":
        only = str(form.get("only") or "").strip()
        if not _PREFIX.match(only):
            raise TaskError("'only keys starting with' may contain letters, digits and _ only")
        args = ["recheck"] + (["--only", only] if only else [])
        source = _folder(form.get("source"), "folder to check", required=False)
        if source:
            args += ["--from", source, "--lines", _folder(form.get("lines"), "line export folder")]
        return args
    lines = _folder(form.get("lines"), "line export folder")
    if not (Path(lines) / "english_lines.jsonl").exists():
        raise TaskError("this folder has no english_lines.jsonl – choose the plugin's export folder "
                        "(<game>\\BepInEx\\LFTTS-export)")
    texts = _file(form.get("texts"), "texts file")
    extra = ["--texts", texts] if texts else []
    if action in ("story", "story-join"):
        only = str(form.get("only") or "").strip()
        if not _PREFIX.match(only):
            raise TaskError("'only keys starting with' may contain letters, digits and _ only")
        return ["story", "--lines", lines, *extra] + (["--join"] if action == "story-join" else []) + \
            (["--only", only] if only and action == "story" else []) + (["--all"] if form.get("all") is True else [])
    if action not in ("render", "dry-run"):
        raise TaskError(f"unknown action: {action}")
    args = ["render", "--lines", lines, *extra]
    engine = str(form.get("engine") or "")
    if engine:
        if engine not in engines:
            raise TaskError(f"unknown engine: {engine}")
        args += ["--engine", engine]
    only = str(form.get("only") or "").strip()
    if not _PREFIX.match(only):
        raise TaskError("'only keys starting with' may contain letters, digits and _ only")
    if only:
        args += ["--only", only]
    try:
        limit = int(form.get("limit") or 0)
    except (TypeError, ValueError):
        raise TaskError("limit must be a number") from None
    if limit < 0:
        raise TaskError("limit must be 0 (all) or more")
    if limit:
        args += ["--limit", str(limit)]
    if form.get("all") is True:
        args.append("--all")
    if action == "dry-run":
        args.append("--dry-run")
    return args


def control_file(cfg: config_mod.Config) -> Path:
    """Pause / stop requests from the watcher for a running long task (read by `crucible recheck`)."""
    return cfg.path(cfg.paths.work_dir) / "task_control.json"


def read_control(cfg: config_mod.Config) -> dict:
    try:
        return json.loads(control_file(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class TaskRunner:
    """Runs one crucible command at a time and keeps its last output lines for the page."""

    def __init__(self, cfg: config_mod.Config):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self.title = ""
        self.output: deque[str] = deque(maxlen=300)
        self.exit_code: int | None = None
        self.started = 0.0

    def start(self, args: list[str]) -> None:
        """Start `crucible <args>`; refuses while another command is still running."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise TaskError("another task is still running – wait until it finishes")
            self.control({})  # a new task starts neither paused nor stopped
            self.title = "crucible " + " ".join(args)
            self.output.clear()
            self.exit_code = None
            self.started = time.time()
            _log.info("watcher started: %s", self.title)
            self._proc = subprocess.Popen(_base(self.cfg) + args, cwd=ROOT, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                          encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
            threading.Thread(target=self._read, args=(self._proc,), daemon=True).start()

    def control(self, state: dict) -> None:
        """Ask the running task to pause, resume or stop (it checks between two files)."""
        f = control_file(self.cfg)
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            pass

    def _read(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self.output.append(line.rstrip())
        self.exit_code = proc.wait()

    def status(self) -> dict:
        running = self._proc is not None and self._proc.poll() is None
        state = read_control(self.cfg) if running else {}
        return {"title": self.title, "running": running, "exit_code": None if running else self.exit_code,
                "started": self.started, "output": list(self.output), "paused": bool(state.get("pause")),
                "stopping": bool(state.get("stop"))}


class LocalWorker:
    """Pairs this computer as a worker (once) and starts worker.cmd in its own window."""

    def __init__(self, cfg: config_mod.Config):
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None

    @property
    def identity_file(self) -> Path:
        return self.cfg.path(self.cfg.paths.work_dir) / "worker" / "identity.json"

    def paired(self) -> bool:
        return self.identity_file.exists()

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def pair(self, code: str, api_port: int) -> str:
        """Pair with this coordinator on 127.0.0.1; returns the command's output."""
        r = subprocess.run(_base(self.cfg) + ["pair", code, "--coordinator", f"127.0.0.1:{api_port}"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           creationflags=_NO_WINDOW)
        if r.returncode != 0:
            raise TaskError("pairing this computer failed: " + (r.stdout + r.stderr).strip()[-300:])
        return r.stdout

    def start(self) -> None:
        """Start worker.cmd in a new window, so it can be watched and closed like a hand-started one."""
        if self.running():
            raise TaskError("the local worker is already running")
        launcher = ROOT / "worker.cmd"
        cmd = ["cmd", "/c", str(launcher)] if launcher.exists() and sys.platform == "win32" else _base(self.cfg) + ["worker"]
        import os
        env = dict(os.environ)
        if self.cfg.source is not None:  # the same settings file as this coordinator
            env["VOICECRUCIBLE_CONFIG"] = str(self.cfg.source)
        self._proc = subprocess.Popen(cmd, cwd=ROOT, creationflags=_NEW_CONSOLE, env=env)
        _log.info("local worker started from the watcher")

    def status(self) -> dict:
        return {"paired": self.paired(), "running": self.running()}


_PICKER = r"""
import sys, tkinter
from tkinter import filedialog
root = tkinter.Tk(); root.withdraw(); root.attributes("-topmost", True)
kind, title, start = sys.argv[1], sys.argv[2], sys.argv[3] or None
if kind == "folder":
    p = filedialog.askdirectory(title=title, initialdir=start, mustexist=True)
elif kind == "zip":
    p = filedialog.askopenfilename(title=title, initialdir=start, filetypes=[("Profile pack", "*.zip")])
elif kind == "wav":
    p = filedialog.askopenfilename(title=title, initialdir=start, filetypes=[("Audio", "*.wav *.flac *.ogg *.mp3")])
else:
    p = filedialog.askopenfilename(title=title, initialdir=start, filetypes=[("JSON lines", "*.jsonl *.json"), ("All", "*.*")])
print(p or "")
"""


def pick(kind: str, title: str, start: str = "") -> str:
    """Show a native folder/file dialog on this computer (separate process: Tk needs its own main thread)."""
    if kind not in ("folder", "file", "wav", "zip"):
        raise TaskError("unknown picker")
    start_dir = start if start and Path(start).is_dir() else ""
    r = subprocess.run([sys.executable, "-c", _PICKER, kind, title[:100], start_dir], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600, creationflags=_NO_WINDOW)
    return r.stdout.strip()


class FormMemory:
    """Remembers the last form values (export folder, engine, ...) in work/watcher.json."""

    KEYS = ("lines", "texts", "engine", "only", "limit", "profile", "output", "takes")

    def __init__(self, cfg: config_mod.Config):
        self.file = cfg.path(cfg.paths.work_dir) / "watcher.json"

    def load(self) -> dict:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return {k: data[k] for k in self.KEYS if k in data}
        except (OSError, ValueError):
            return {}

    def save(self, values: dict) -> None:
        """Merge the given known keys into the remembered values."""
        data = self.load()
        data.update({k: values.get(k) for k in self.KEYS if k in values})
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            pass


def profiles_overview(root: Path) -> list[dict]:
    """Every installed profile with its characters and how many reference clips are missing."""
    from voicecrucible.installer import profiles
    out = []
    for meta in profiles.installed(root):
        folder = profiles.profiles_dir(root) / meta["folder"]
        try:
            rows = voices(folder)
            chars, missing, error = len({r["character"] for r in rows}), sum(not r["exists"] for r in rows), ""
        except Exception as e:  # noqa: BLE001 - a broken profile is listed with its error
            chars, missing, error = 0, 0, str(e)
        out.append({"name": meta["folder"], "title": meta.get("title", ""), "version": meta.get("version", ""),
                    "bundled": meta["folder"] in BUNDLED_PROFILES, "characters": chars, "missing": missing,
                    "error": error})
    return out


def open_folder(folder: Path) -> None:
    """Show a folder in Explorer (only folders inside the profiles folder are passed in)."""
    import os
    if not folder.is_dir():
        raise TaskError(f"folder not found: {folder}")
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: S606 - opens Explorer on a known local folder
    else:
        subprocess.Popen(["xdg-open", str(folder)])


BUNDLED_PROFILES = ("lethalfantasy", "template")


def voices(profile_folder: Path) -> list[dict]:
    """Reference clips of the active profile: character, engine, file, whether it exists and its length."""
    import soundfile as sf

    from voicecrucible.lethalfantasy import profile as profile_mod
    out = []
    for c in profile_mod.load(profile_folder).characters.values():
        for engine, path in sorted(c.voices.items()):
            row = {"character": c.name, "folder": c.folder, "engine": engine, "file": str(path),
                   "exists": path.exists(), "seconds": None, "mtime": int(path.stat().st_mtime) if path.exists() else 0}
            if path.exists():
                try:
                    row["seconds"] = round(sf.info(str(path)).duration, 1)
                except RuntimeError:
                    row["seconds"] = None
            out.append(row)
    return out


def voice_path(profile_folder: Path, character: str, engine: str) -> Path:
    """The configured reference clip of one character (only paths from the profile, never from the page)."""
    from voicecrucible.lethalfantasy import profile as profile_mod
    c = profile_mod.load(profile_folder).characters.get(character)
    if c is None or engine not in c.voices:
        raise TaskError(f"no voice slot for {character} / {engine}")
    return c.voices[engine]


def replace_voice(profile_folder: Path, character: str, engine: str, source: str) -> Path:
    """Copy a chosen audio file (converted to WAV) into the profile's slot; the old clip is kept as .bak.wav."""
    import soundfile as sf
    if profile_folder.name in BUNDLED_PROFILES:
        raise TaskError(f"'{profile_folder.name}' is a bundled profile (updates replace it). Make your own copy first: "
                        f"crucible profile new mine --from lethalfantasy, then set [render] profile = \"mine\" in "
                        f"voicecrucible.toml and restart the coordinator.")
    target = voice_path(profile_folder, character, engine)
    src = Path(source)
    if not src.is_file():
        raise TaskError(f"file not found: {src}")
    try:
        audio, rate = sf.read(str(src), always_2d=True)
    except RuntimeError as e:
        raise TaskError(f"cannot read this audio file: {e}") from None
    seconds = len(audio) / rate
    if not 3 <= seconds <= 60:
        raise TaskError(f"the clip is {seconds:.1f} s long – use 5–30 s of clean speech (3–60 s accepted)")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.replace(target.with_name(target.stem + ".bak.wav"))
    sf.write(str(target), audio.mean(axis=1), rate, subtype="PCM_16")
    _log.info("reference voice for %s (%s) replaced in the watcher: %s", character, engine, src.name)
    return target


def local_worker_id(cfg: config_mod.Config) -> str:
    """The worker id of this computer ('' when it is not paired)."""
    try:
        return json.loads((cfg.path(cfg.paths.work_dir) / "worker" / "identity.json").read_text(encoding="utf-8"))["worker_id"]
    except (OSError, ValueError, KeyError):
        return ""


def run_setup(cfg: config_mod.Config, registry, worker: LocalWorker, stop_coordinator) -> None:
    """Close this computer's worker, open setup.cmd in its own window, then end the coordinator.

    Setup replaces packages of runtime\venv, which the coordinator and the worker use (files in use are locked
    on Windows), so they must be closed first. Runs in the background; the page has already been answered.
    """
    import os
    wid = local_worker_id(cfg)
    if wid and registry.set_mode(wid, "shutdown"):
        _log.info("run setup: shutting down the local worker")
        for _ in range(60):  # it finishes or hands back its batch, then exits
            if not any(w["worker_id"] == wid and w["online"] and w.get("exit_reason", "") == ""
                       for w in registry.snapshot()):
                break
            time.sleep(1)
    if worker.running() and worker._proc is not None:  # still open: close its window
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(worker._proc.pid)], capture_output=True)
    # the window stays open at the end of setup ("press any key"), so the user sees when it is done
    env = {k: v for k, v in os.environ.items() if k not in ("VOICECRUCIBLE_CONFIG", "VC_NO_PAUSE")}
    env["VC_RESTART_COORDINATOR"] = "1"  # setup.cmd starts the coordinator again when it succeeded
    if cfg.source is not None:  # ... with the same settings file
        env["VOICECRUCIBLE_CONFIG"] = str(cfg.source)
    setup = ROOT / "setup.cmd"
    _log.info("run setup: opening %s and closing the coordinator", setup)
    # passed as one string: cmd /c strips the outer quotes and keeps the quoted path (a list would escape them as \")
    subprocess.Popen(f'cmd /c "timeout /t 5 /nobreak >nul & call "{setup}""', cwd=ROOT, env=env,
                     creationflags=_NEW_CONSOLE)
    stop_coordinator()


def diagnose_report(cfg: config_mod.Config) -> str:
    """`crucible diagnose` on this computer (separate process, so the coordinator does not load torch);
    the report has personal data removed (IPs, computer and user names, tokens)."""
    r = subprocess.run(_base(cfg) + ["diagnose"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180, creationflags=_NO_WINDOW)
    report = cfg.path(cfg.paths.log_dir) / "diagnose.txt"
    if r.returncode != 0 or not report.exists():
        raise TaskError("diagnose failed: " + (r.stdout + r.stderr).strip()[-300:])
    return report.read_text(encoding="utf-8")


def export_info(folder: str) -> dict:
    """What the plugin's line export holds: texts, dialogue lines per speaker and type, the expressions (emotions)."""
    from collections import Counter
    p = Path(str(folder))
    texts_file, events_file = p / "english_lines.jsonl", p / "dialogue_events.jsonl"
    if not texts_file.is_file():
        raise TaskError("no english_lines.jsonl in this folder")

    def rows(f: Path) -> list[dict]:
        out = []
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    texts = rows(texts_file)
    events = rows(events_file) if events_file.is_file() else []
    expressions = Counter(str(e.get("expression", "")) for e in events if e.get("expression"))
    return {"texts": len(texts), "dialogue_lines": len({e.get("key") for e in events}),
            "speakers": dict(Counter(str(e.get("character", "?")) for e in events).most_common()),
            "types": dict(Counter(str(e.get("type", "?")) for e in events).most_common()),
            "expressions": dict(expressions.most_common()), "has_events": events_file.is_file()}
