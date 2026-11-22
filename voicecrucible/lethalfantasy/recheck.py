"""`crucible recheck`: run today's checks on voice files that already exist – no rendering.

Without --from: the finished lines of the queue (their files in the output folder). With --from <folder>: a voice
pack anywhere, e.g. the one in the game. That folder is only read: its files are copied into the output folder
(a different file already there is kept as <name>.bak.<ext>) and checked there. Lines that fail go to the
watcher's Problems (listen, Accept, Redo, Skip); the files stay.
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from voicecrucible.core import audio, log
from voicecrucible.core.config import Config
from voicecrucible.core.queue import JobQueue

_log = log.get(__name__)


def _find(source: Path, language: str, folder: str, stem: str) -> Path | None:
    """A line's file in a pack folder given as voices\\<lang>, voices, the pack root – or one character's folder
    (e.g. voices\\en\\AKIPO: then only that character's lines are found)."""
    places = [base / folder for base in (source, source / language, source / "voices" / language)]
    if source.name.upper() == folder.upper():
        places.append(source)
    for place in places:
        for ext in ("ogg", "wav"):
            p = place / f"{stem}.{ext}"
            if p.is_file():
                return p
    return None


def _import(cfg: Config, args: argparse.Namespace, queue: JobQueue, output_root: Path) -> int:
    """Copy the pack's files for the export's lines into the output folder and record them as done."""
    from voicecrucible.coordinator import results
    from voicecrucible.coordinator.assets import AssetStore
    from voicecrucible.lethalfantasy import build, commands, lines
    source = Path(args.source).resolve()
    if any(part.lower() == "bepinex" for part in output_root.parts):
        raise SystemExit("the output folder must not be inside the game")  # also refused by the config check
    profile = commands._load_profile(cfg, args.lines)
    built = build.build(profile, lines.read_export(args.lines, profile, None), "chatterbox", {},
                        AssetStore(cfg.path(cfg.paths.work_dir) / "coordinator" / "assets").add, args.only or "",
                        cfg.render.characters, cfg.render.language)
    folders = {ln.character.upper() for ln in built.lines}
    if source.name.upper() in folders:  # one character's folder (e.g. voices\en\AKIPO): only that character's lines
        built.lines = [ln for ln in built.lines if ln.character.upper() == source.name.upper()]
    found, copied, kept = [], 0, 0
    made = queue.made_here()
    for ln in built.lines:
        src = _find(source, cfg.render.language, ln.character, ln.file_stem)
        if src is None:
            continue
        target = results.output_path(output_root, cfg.render.language, ln, src.suffix.lstrip("."))
        if (ln.key, ln.character, ln.variant) in made and target.exists():
            kept += 1  # made or fixed in Voice Crucible: your version stays (and is checked), not the folder's
            continue
        if not (target.exists() and target.read_bytes() == src.read_bytes()):  # check the folder's own file
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():  # your file is kept, not lost
                target.replace(target.with_name(f"{target.stem}.bak{target.suffix}"))
            shutil.copyfile(src, target)
            copied += 1
        found.append((ln, target.relative_to(output_root).as_posix()))
    if not found and not kept and built.lines:
        where = ", ".join(sorted({ln.character for ln in built.lines}))
        raise LookupError(f"0 of {len(built.lines)} line(s) have a file in {source} – these lines are in the "
                          f"character folder(s) {where}. Choose the language folder (all characters) or one of those.")
    recorded = queue.record_existing("chatterbox", found)
    _log.info("from %s: %d of %d line(s) have a file, %d copied into the output folder, %d recorded",
              source, len(found) + kept, len(built.lines), copied, recorded)
    if kept:
        _log.info("%d line(s) kept as they are: made or fixed in Voice Crucible – your version is checked, not the "
                  "folder's", kept)
    return len(found)


def recheck(cfg: Config, args: argparse.Namespace) -> int:
    """Check existing voice files with the current checks; failing lines go to the problems."""
    from voicecrucible.checks.base import Candidate, CheckSet, summary
    from voicecrucible.coordinator import run
    from voicecrucible.coordinator.assets import AssetStore
    output_root = cfg.path(cfg.paths.output_dir)
    work = cfg.path(cfg.paths.work_dir) / "coordinator"
    queue = JobQueue(work / "queue.sqlite", max_attempts=cfg.checks.max_attempts)
    try:
        if args.source:
            if args.lines is None:
                _log.error("--from needs the game's line export too: crucible recheck --lines <export> --from <pack>")
                return 1
            try:
                _import(cfg, args, queue, output_root)
            except LookupError as e:
                _log.error("%s", e)
                return 1
        todo = queue.done_lines(args.only or "")
        if not todo:
            _log.error("no finished lines with a voice file to check")
            return 1
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            _log.error("the checks are not installed on this computer – run setup.cmd and choose 'checks'")
            return 1
        checks = CheckSet(device)
        checks.configure(run.check_settings(cfg))
        store = AssetStore(work / "assets")
        failed = 0
        _log.info("checking %d voice file(s) on %s", len(todo), device)
        _log.info("re-check progress: 0 / %d checked, 0 failed", len(todo))  # read by the watcher's progress bar
        from voicecrucible.watcher.tasks import read_control
        for i, (line, output) in enumerate(todo, 1):
            ctl = read_control(cfg)
            if ctl.get("pause"):
                _log.info("re-check paused in the watcher after %d / %d", i - 1, len(todo))
                while ctl.get("pause") and not ctl.get("stop"):
                    time.sleep(1)
                    ctl = read_control(cfg)
                if not ctl.get("stop"):
                    _log.info("re-check resumed")
            if ctl.get("stop"):
                _log.info("re-check stopped in the watcher: %d / %d checked, %d failed", i - 1, len(todo), failed)
                return 0
            path = output_root / output
            if not path.is_file():
                continue
            y, sr = audio.decode(path.read_bytes())
            ok, reason = summary(checks.run(Candidate(line, y, sr, store.get(line.voice) if line.voice else None)))
            if not ok:
                queue.mark_problem(line.uid, reason)
                failed += 1
                _log.info("%s: %s", line.file_stem, reason)
            if i % 10 == 0 or i == len(todo):
                _log.info("re-check progress: %d / %d checked, %d failed", i, len(todo), failed)
        _log.info("re-check done: %d checked, %d failed – listen to them in the watcher (Problems)", len(todo), failed)
        return 0
    finally:
        queue.close()
