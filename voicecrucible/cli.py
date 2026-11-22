"""Command line entry point: `crucible <command>`. Each command lives in its own package."""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from voicecrucible import __version__
from voicecrucible.core import config as config_mod
from voicecrucible.core import log

# command -> one-line help; commands without a handler yet report that they are planned
COMMANDS = {
    "setup": "check the GPU and install the components listed in downloads.toml",
    "pair": "pair this worker with a coordinator using its 6-digit code",
    "coordinator": "run the job queue and the watcher on this machine",
    "worker": "render jobs on this machine's GPU",
    "direct": "create directions.json (acting directions) before rendering",
    "render": "queue the lines to render",
    "report": "summarise a finished render (passed, failed, reasons)",
    "config": "show the effective configuration and check it for errors",
    "diagnose": "collect technical facts for a bug report (personal data removed)",
    "story": "Memory Orb audiobook: queue its parts, then --join them into pages",
    "update": "check GitHub for a new version and install it after you confirm (signature verified)",
    "profile": "create a profile from the template (new), list profiles, or install a shared profile pack",
}


def _cmd_config(cfg: config_mod.Config) -> int:
    """Print the validated configuration, section by section."""
    for name, section in asdict(cfg).items():
        if isinstance(section, dict):
            print(f"[{name}]")
            for key, value in section.items():
                print(f"  {key} = {value!r}")
    print(f"(relative paths are resolved against {cfg.base_dir})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with one sub-command per entry in COMMANDS."""
    parser = argparse.ArgumentParser(prog="crucible", description="Voice Crucible – voice packs for LethalFantasy TTS")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", type=Path, help="config file (default: voicecrucible.toml if present)")
    parser.add_argument("-v", "--verbose", action="store_true", help="more detailed log output")
    sub = parser.add_subparsers(dest="command", required=True)
    cmds = {name: sub.add_parser(name, help=text, description=text) for name, text in COMMANDS.items()}
    cmds["pair"].add_argument("code", help="the pairing code shown by the coordinator (e.g. ABCDE-FGHJK)")
    cmds["pair"].add_argument("--coordinator", default="", help="coordinator host[:port] if it is not found automatically")
    r = cmds["render"]
    r.add_argument("--lines", type=Path, help="folder with the plugin's line export (english_lines.jsonl, dialogue_events.jsonl)")
    r.add_argument("--texts", type=Path, help="texts in the pack language ({\"key\",\"text\"} JSON lines, e.g. "
                   "from Weblate); default: the export's English texts")
    r.add_argument("--engine", default="", help="engine to use (default: [render] engine)")
    r.add_argument("--only", default="", help="only keys starting with this prefix, e.g. CHARACTER_DIALOGUE_EVENT_HUG")
    r.add_argument("--limit", type=int, default=0, help="queue at most N lines (for a quick test)")
    r.add_argument("--dry-run", action="store_true", help="show what would be queued, queue nothing")
    r.add_argument("--all", action="store_true", help="also lines that already have a voice file (render them again)")
    r.add_argument("--retry-failed", action="store_true", help="queue the lines that failed for good again")
    r.add_argument("--cancel", action="store_true", help="cancel the render: remove waiting and rendering lines "
                   "(finished voice files are kept)")
    r.add_argument("--test", type=int, metavar="N", help="queue N test lines (beep engine, no model needed)")
    r.add_argument("--profile", default="", help="profile to use instead of [render] profile")
    r.add_argument("--output", default="", help="voice pack folder to use instead of [paths] output_dir")
    st = cmds["story"]
    st.add_argument("--lines", type=Path, required=True, help="folder with the plugin's line export")
    st.add_argument("--texts", type=Path, help="page texts in another language (default: the export's English)")
    st.add_argument("--join", action="store_true", help="join the rendered parts into STORY/<page>.ogg")
    st.add_argument("--only", default="", help="only parts whose key starts with this, e.g. TWINS_TEASER_10__p005")
    st.add_argument("--all", action="store_true", help="also parts that are already rendered; with --join: replace "
                    "existing pages (old ones kept as .bak.ogg)")
    st.add_argument("--profile", default="", help="profile to use instead of [render] profile")
    st.add_argument("--output", default="", help="voice pack folder to use instead of [paths] output_dir")
    cmds["report"].add_argument("--output", default="", help="voice pack folder (default: [paths] output_dir)")
    s = cmds["setup"]
    s.add_argument("--components", default="", help="comma-separated, e.g. checks,chatterbox,qwen,seedvc "
                   "(default: asked; see downloads.toml)")
    s.add_argument("--yes", action="store_true", help="answer every question with its default")
    cmds["profile"].add_argument("action", choices=["new", "list", "install"])
    cmds["profile"].add_argument("target", nargs="?", default="",
                                 help="new: name of the new profile; install: a profile zip")
    cmds["profile"].add_argument("--from", dest="source", default="template",
                                 help="new: copy this profile (e.g. lethalfantasy) instead of the empty template")
    cmds["update"].add_argument("--rollback", action="store_true", help="go back to the version before the last update")
    d = cmds["direct"]
    d.add_argument("--lines", type=Path, required=True, help="folder with the plugin's line export")
    d.add_argument("--only", default="", help="only keys starting with this prefix")
    d.add_argument("--limit", type=int, default=0, help="direct at most N scenes")
    d.add_argument("--yes", action="store_true", help="do not ask before sending lines to the API")
    return parser


def _find_config(arg: Path | None) -> Path | None:
    """Use the given config file, else voicecrucible.toml in the current folder, else in the install folder."""
    if arg is not None:
        return arg
    import os
    if os.environ.get("VOICECRUCIBLE_CONFIG"):  # set by the watcher for the local worker it starts
        return Path(os.environ["VOICECRUCIBLE_CONFIG"])
    from voicecrucible.installer import layout
    for candidate in (Path("voicecrucible.toml"), layout.ROOT / "voicecrucible.toml"):
        if candidate.exists():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    """Parse the arguments, load the config and run the chosen command."""
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    from voicecrucible.installer import layout
    layout.apply()  # caches and models stay inside the install folder, also without a launcher
    args = build_parser().parse_args(argv)
    try:
        config_file = _find_config(args.config)
        cfg = config_mod.load(config_file)
        if config_file is None:  # no settings file: folders are relative to the install folder, not the current one
            cfg.base_dir = layout.ROOT
        if getattr(args, "profile", ""):  # render/story --profile: this run only, the config file is not changed
            cfg.render.profile = args.profile
        if getattr(args, "output", ""):  # render/story --output: this run only
            cfg.paths.output_dir = str(Path(args.output).resolve())
            config_mod.validate(cfg)  # e.g. never inside the game's BepInEx folder
    except (OSError, config_mod.ConfigError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2
    if args.command == "config":
        return _cmd_config(cfg)
    log.setup(cfg.path(cfg.paths.log_dir), args.command, args.verbose)
    handler = _HANDLERS.get(args.command)
    if handler is None:
        log.get("crucible").warning("'%s' is planned but not implemented yet", args.command)
        return 1
    return handler(cfg, args)


def _cmd_coordinator(cfg: config_mod.Config, _args: argparse.Namespace) -> int:
    """Run the coordinator."""
    from voicecrucible.coordinator import run
    return run.run(cfg)


def _cmd_worker(cfg: config_mod.Config, _args: argparse.Namespace) -> int:
    """Run the worker."""
    from voicecrucible.worker import client
    return client.run(cfg)


def _cmd_pair(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Pair this worker with a coordinator."""
    from voicecrucible.worker import client
    try:
        ident = client.pair(cfg, args.code, args.coordinator)
    except (client.PairingError, OSError) as e:
        log.get("crucible").error("pairing failed: %s", e)
        return 1
    log.get("crucible").info("paired with coordinator %s at %s:%d – start the worker with: crucible worker",
                             ident.coordinator_id, ident.host, ident.port)
    return 0


def _cmd_render(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Queue lines on this (coordinator) machine: the game's lines (--lines) or test beeps (--test)."""
    from voicecrucible.core.jobs import Line
    from voicecrucible.core.queue import JobQueue
    if args.cancel:
        queue = JobQueue(cfg.path(cfg.paths.work_dir) / "coordinator" / "queue.sqlite")
        n = queue.cancel()
        queue.close()
        log.get("crucible").info("render cancelled: %d waiting/rendering line(s) removed (finished files are kept)", n)
        return 0
    if args.retry_failed:
        queue = JobQueue(cfg.path(cfg.paths.work_dir) / "coordinator" / "queue.sqlite")
        n = queue.retry_failed()
        queue.close()
        log.get("crucible").info("%d failed line(s) queued again with fresh attempts", n)
        return 0
    if not args.test:
        if args.lines is None:
            log.get("crucible").error("give the line export folder: crucible render --lines <folder>")
            return 1
        from voicecrucible.lethalfantasy import commands
        return _with_profile(commands.render, cfg, args)
    queue = JobQueue(cfg.path(cfg.paths.work_dir) / "coordinator" / "queue.sqlite")
    lines = [Line(key=f"TEST_LINE_{i:04d}", character="TEST", text="test " * (i % 10 + 1))
             for i in range(1, args.test + 1)]
    added = queue.add("test", lines)
    queue.close()
    log.get("crucible").info("%d test line(s) queued (%d already there)", added, len(lines) - added)
    return 0


def _cmd_direct(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Create acting directions with the configured AI."""
    from voicecrucible.lethalfantasy import commands
    return _with_profile(commands.direct, cfg, args)


def _with_profile(command, cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Run a command that needs the profile; a missing profile is a clear message, not a traceback."""
    from voicecrucible.lethalfantasy.profile import ProfileMissing
    try:
        return command(cfg, args)
    except ProfileMissing as e:
        log.get("crucible").error("%s", e)
        return 1


def _cmd_profile(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Install or list profiles."""
    from voicecrucible.installer import profiles
    if args.action == "new":
        return profiles.new_command(args.target, args.source)
    if args.action == "install":
        return profiles.install_command(Path(args.target) if args.target else None)
    return profiles.list_command(cfg.render.profile)


def _cmd_report(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Summarise the render."""
    from voicecrucible.lethalfantasy import commands
    return commands.report(cfg, args)


def _cmd_setup(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Install or change components."""
    from voicecrucible.installer import setup
    return setup.run(cfg, args)


def _cmd_diagnose(cfg: config_mod.Config, _args: argparse.Namespace) -> int:
    """Bug report helper."""
    from voicecrucible.installer import diagnose
    return diagnose.run(cfg)


def _cmd_update(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Manual update."""
    from voicecrucible.installer import update
    return update.run(args, cfg.coordinator.watcher_port)


_HANDLERS = {"coordinator": _cmd_coordinator, "worker": _cmd_worker, "pair": _cmd_pair, "render": _cmd_render,
             "direct": _cmd_direct, "report": _cmd_report, "setup": _cmd_setup, "diagnose": _cmd_diagnose,
             "update": _cmd_update, "profile": _cmd_profile, "story": lambda c, a: _cmd_story(c, a)}


def _cmd_story(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Memory Orb audiobook."""
    from voicecrucible.lethalfantasy import commands
    return _with_profile(commands.story, cfg, args)


if __name__ == "__main__":
    sys.exit(main())
