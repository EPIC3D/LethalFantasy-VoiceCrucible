"""`crucible render` and `crucible direct` for LethalFantasy: read the export, direct, queue."""

from __future__ import annotations

import argparse
from itertools import groupby
from pathlib import Path
from urllib.parse import urlparse

from voicecrucible.coordinator import results
from voicecrucible.coordinator.assets import AssetStore
from voicecrucible.coordinator.discovery import is_local_address
from voicecrucible.coordinator.run import profile_dir
from voicecrucible.core import languages, log
from voicecrucible.core.config import Config
from voicecrucible.core.queue import JobQueue
from voicecrucible.directors import base as directions
from voicecrucible.directors.base import SceneLine
from voicecrucible.engines import base as engines
from voicecrucible.lethalfantasy import build, filters, lines, profile as profile_mod

_log = log.get("crucible")


def directions_path(cfg: Config) -> Path:
    """Where `crucible direct` writes its directions."""
    return cfg.path(cfg.paths.work_dir) / "directions.json"


def load_directions(cfg: Config) -> dict[str, dict]:
    """Directions for rendering according to [director] mode (none = no directions)."""
    mode = cfg.director.mode
    if mode == "file":
        return directions.load(cfg.path(cfg.director.file))
    if mode == "api":
        path = directions_path(cfg)
        if not path.exists():
            _log.warning("no directions yet – run 'crucible direct' first; rendering without directions")
            return {}
        return directions.load(path)
    return {}


def _has_output(root: Path, language: str, line) -> bool:
    """True when a voice file for this line already exists in the output folder."""
    try:
        return any(results.output_path(root, language, line, ext).exists() for ext in results.AUDIO_EXTENSIONS)
    except results.UnsafeName:
        return False


def _load_profile(cfg: Config, export: Path) -> profile_mod.Profile:
    """Load the profile; speakers new in this game version are added to characters.json first."""
    folder = profile_dir(cfg)
    for name in profile_mod.add_new_characters(folder, lines.speakers(export)):
        _log.warning("new character '%s' found in the game export – added to %s. To render its lines, put a "
                     "reference clip at %s (and check its folder name and description)", name,
                     folder / "characters.json", folder / "voices" / "chatterbox" / f"{name}.wav")
    return profile_mod.load(folder)


def render(cfg: Config, args: argparse.Namespace) -> int:
    """Queue the lines of the export for rendering (or only show what would be queued with --dry-run)."""
    engine = args.engine or cfg.render.engine
    if engine not in engines.available():
        _log.error("unknown engine '%s' (known: %s)", engine, ", ".join(engines.available()))
        return 1
    lang = cfg.render.language
    if engine in ("qwen", "qwen_vc") and languages.qwen_name(lang) is None:
        _log.error("engine '%s' cannot speak language '%s'", engine, lang)
        return 1
    if engine in languages.ENGLISH_ONLY_ENGINES and lang != "en":
        _log.warning("engine '%s' speaks English only – '%s' lines will sound wrong", engine, lang)
    if lang != "en" and args.texts is None:
        _log.warning("[render] language = '%s' but no --texts file given: the English texts are used", lang)
    profile = _load_profile(cfg, args.lines)
    source = lines.read_export(args.lines, profile, args.texts)
    folder = cfg.path(cfg.paths.work_dir) / "coordinator"
    store = AssetStore(folder / "assets")
    result = build.build(profile, source, engine, load_directions(cfg), store.add, args.only, cfg.render.characters,
                         lang)
    if result.missing_voices:
        _log.warning("no reference voice for %s – their lines are skipped. Put a clip per character into %s "
                     "(file names are set in characters.json; see docs/PROFILES.md).",
                     ", ".join(sorted(result.missing_voices)), profile.folder / "voices" / engine.replace("qwen_vc", "acting"))
    if not result.lines:
        _log.error("nothing to queue")
        return 1
    lines_to_queue = result.lines
    if not args.all:  # extend a pack: lines that already have a voice file are not rendered again
        output_root = cfg.path(cfg.paths.output_dir)
        lines_to_queue = [ln for ln in result.lines if not _has_output(output_root, lang, ln)]
        if len(lines_to_queue) < len(result.lines):
            _log.info("skipped %d line(s): already rendered (use --all to render them again)",
                      len(result.lines) - len(lines_to_queue))
    queued = lines_to_queue[:args.limit] if args.limit else lines_to_queue
    for reason, n in sorted(result.skipped.items()):
        _log.info("skipped %d line(s): %s", n, reason)
    if args.dry_run:
        for ln in queued[:5]:
            _log.info("example: %s/%s  %r  %s", ln.character, ln.file_stem, ln.text, ln.params)
        _log.info("dry run: %d line(s) would be queued for engine '%s'", len(queued), engine)
        return 0
    queue = JobQueue(folder / "queue.sqlite", max_attempts=cfg.checks.max_attempts)
    added = queue.add(engine, queued)
    queue.close()
    _log.info("%d line(s) queued for engine '%s' (%d were already queued)", added, engine, len(queued) - added)
    return 0


def story(cfg: Config, args: argparse.Namespace) -> int:
    """`crucible story --lines <export>`: queue the audiobook parts; with --join: build the finished pages."""
    from voicecrucible.lethalfantasy import story as story_mod
    profile = _load_profile(cfg, args.lines)
    scfg = story_mod.load_config(profile.folder)
    if scfg is None:
        _log.error("the profile '%s' has no story.json – no audiobook settings", profile.folder.name)
        return 1
    texts = {r["key"]: r["text"] for r in lines._jsonl(args.texts or args.lines / "english_lines.jsonl")}
    pages = {k: v for k, v in texts.items() if k.startswith(scfg.prefix)}
    if not pages:
        _log.error("no pages starting with %s in the export", scfg.prefix)
        return 1
    folder = cfg.path(cfg.paths.work_dir) / "coordinator"
    try:
        parts = story_mod.build_lines(pages, scfg, profile.lexicon, AssetStore(folder / "assets").add)
    except FileNotFoundError as e:
        _log.error("%s", e)
        return 1
    output_root, lang = cfg.path(cfg.paths.output_dir), cfg.render.language
    if args.join:
        joined, missing = story_mod.join_pages(output_root, lang, scfg, parts)
        for page, absent in sorted(missing.items()):
            _log.warning("%s not ready – %d part(s) missing", page, len(absent))
        _log.info("%d page(s) written to %s", len(joined), output_root / "voices" / lang / scfg.folder)
        return 0 if not missing else 1
    todo = parts if args.all else [ln for ln in parts if not _has_output(output_root, lang, ln)]
    queue = JobQueue(folder / "queue.sqlite", max_attempts=cfg.checks.max_attempts)
    added = queue.add("chatterbox", todo)
    queue.close()
    _log.info("audiobook: %d page(s), %d part(s); %d queued (%d already rendered). When they are done: "
              "crucible story --lines <export> --join", len(pages), len(parts), added, len(parts) - len(todo))
    return 0


def _scenes(source: list[lines.SourceLine], only: str) -> list[tuple[str, list[SceneLine]]]:
    """Lines grouped into scenes in game order; the player's choices are context only."""
    picked = sorted((s for s in source if not only or s.key.startswith(only)), key=lambda s: (s.scene, s.order))
    out = []
    for scene, group in groupby(picked, key=lambda s: s.scene):
        out.append((scene, [SceneLine(s.key, s.character if filters.is_voiced(s) else "PLAYER", s.text,
                                      s.expression, filters.is_voiced(s)) for s in group]))
    return out


def direct(cfg: Config, args: argparse.Namespace) -> int:
    """Create acting directions with the configured API, scene by scene; resumable."""
    from voicecrucible.directors.api import ApiDirector, ApiDirectorError
    d = cfg.director
    if d.mode != "api":
        _log.error("set [director] mode = \"api\" (and api_base, model) to create directions with an AI")
        return 1
    profile = _load_profile(cfg, args.lines)
    out = directions_path(cfg)
    done = directions.load(out) if out.exists() else {}
    todo = [(name, sl) for name, sl in _scenes(lines.read_export(args.lines, profile), args.only)
            if any(ln.voiced and ln.key not in done for ln in sl)]
    if args.limit:
        todo = todo[:args.limit]
    n_lines = sum(len(sl) for _, sl in todo)
    host = urlparse(d.api_base).hostname or ""
    where = "this computer / local network" if host == "localhost" or is_local_address(host) else f"the internet ({host})"
    print(f"{len(todo)} scene(s), {n_lines} line(s) of game text will be sent to {d.api_base} "
          f"– {where} – model '{d.model}'.")
    if not args.yes and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
        return 1
    director = ApiDirector(d.api_base, d.model, (profile.folder / "director_brief.md").read_text("utf-8"),
                           d.api_key_env)
    failed = 0
    for i, (name, scene_lines) in enumerate(todo, 1):
        try:
            done.update(director.direct(name, scene_lines))
            directions.save(out, done)
            _log.info("[%d/%d] %s: directed", i, len(todo), name)
        except (ApiDirectorError, OSError, KeyError, ValueError) as e:
            failed += 1
            _log.warning("[%d/%d] %s: %s", i, len(todo), name, e)
    _log.info("directions saved to %s (%d line(s)); %d scene(s) failed – run again to retry them", out, len(done), failed)
    return 0 if not failed else 1


def report(cfg: Config, _args: argparse.Namespace) -> int:
    """Summary of the queue and a report.tsv of lines with problems."""
    queue = JobQueue(cfg.path(cfg.paths.work_dir) / "coordinator" / "queue.sqlite")
    counts = queue.counts()
    problems = queue.recent_problems(limit=1_000_000)
    queue.close()
    out = cfg.path(cfg.paths.output_dir) / "report.tsv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("folder\tfile\tstate\tattempts\treason\n")
        for p in problems:
            stem = p["key"] + (f"__{p['variant']}" if p["variant"] else "")
            state = "failed – best take used" if p["status"] == "failed" and p["best_take_used"] else p["status"]
            f.write(f"{p['character']}\t{stem}\t{state}\t{p['attempts']}\t{p['reason']}\n")
    print(" · ".join(f"{k}: {v}" for k, v in counts.items()))
    print(f"{len(problems)} line(s) with problems listed in {out}")
    return 0
