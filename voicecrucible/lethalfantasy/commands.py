"""`crucible render` and `crucible direct` for LethalFantasy: read the export, direct, queue."""

from __future__ import annotations

import argparse
import json
import re
import time
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
from voicecrucible.directors import status as director_status
from voicecrucible.directors.base import SceneLine
from voicecrucible.engines import base as engines
from voicecrucible.lethalfantasy import build, emotions, filters, lines, profile as profile_mod

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
    if result.missing_voices and engine == "breeze":
        _log.warning("no Breeze reference for %s – their lines are skipped. Breeze needs, per character, a recording "
                     "of the profile's reference_text.txt (word for word) in %s – create them with "
                     "'crucible reference' (see docs/PROFILES.md).", ", ".join(sorted(result.missing_voices)),
                     profile.folder / "voices" / "reference")
    elif result.missing_voices:
        _log.warning("no reference voice for %s – their lines are skipped. Put a clip per character into %s "
                     "(file names are set in characters.json; see docs/PROFILES.md).",
                     ", ".join(sorted(result.missing_voices)), profile.folder / "voices" / engine.replace("qwen_vc", "acting"))
    if not result.lines:
        from voicecrucible.lethalfantasy import story as story_mod
        scfg = story_mod.load_config(profile.folder)
        if args.only and scfg is not None and (args.only.startswith(scfg.prefix) or scfg.prefix.startswith(args.only)):
            _log.error("nothing to queue: '%s' is an audiobook page – use 'Audiobook: queue pages' in the watcher "
                       "(crucible story --lines <export> --only %s)", args.only, args.only)
        else:
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
    added = queue.add(engine, queued, again=args.all)
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
        parts = story_mod.build_lines(pages, scfg, profile.lexicon, AssetStore(folder / "assets").add,
                                      cfg.render.language, profile.sounds)
    except FileNotFoundError as e:
        _log.error("%s", e)
        return 1
    output_root, lang = cfg.path(cfg.paths.output_dir), cfg.render.language
    if args.join:
        queue = JobQueue(folder / "queue.sqlite")
        skipped = queue.skipped_keys()
        queue.close()
        joined, missing = story_mod.join_pages(output_root, lang, scfg, parts, replace=args.all, skipped=skipped)
        kept = len({ln.key.rsplit("__p", 1)[0] for ln in parts}) - len(joined) - len(missing)
        if kept:
            _log.info("%d page(s) already exist and were kept (maybe edited by hand) – --all replaces them, "
                      "the old files are kept as .bak.ogg", kept)
        for page, absent in sorted(missing.items()):
            _log.warning("%s not ready – %d part(s) missing", page, len(absent))
        _log.info("%d page(s) written to %s", len(joined), output_root / "voices" / lang / scfg.folder)
        return 0 if not missing else 1
    only = getattr(args, "only", "") or ""
    todo = [ln for ln in parts if ln.key.startswith(only)]
    if not args.all:
        todo = [ln for ln in todo if not _has_output(output_root, lang, ln)]
    queue = JobQueue(folder / "queue.sqlite", max_attempts=cfg.checks.max_attempts)
    added = queue.add("chatterbox", todo, again=args.all)
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
                                      s.expression, filters.is_voiced(s),
                                      s.order[1] if len(s.order) > 2 else -1) for s in group]))
    return out


def _scene_context_builder(folder: Path, notes_file: Path | None):
    """A function giving the director what it cannot see in the text: the physical situation (scene_sheets.json),
    the translators' note (--notes, JSON lines with key + note) and the meaning of the expressions used."""
    def read(name: str) -> dict:
        p = folder / name
        return json.loads(p.read_text("utf-8")) if p.exists() else {}
    sheets = {k: v for k, v in read("scene_sheets.json").items() if not k.startswith("_")}
    meanings = {k: v.get("meaning", "") for k, v in read("expressions.json").items()
                if isinstance(v, dict) and v.get("meaning")}
    notes: dict[str, str] = {}
    if notes_file:
        with open(notes_file, encoding="utf-8") as f:
            for row in map(json.loads, filter(str.strip, f)):
                if row.get("note"):
                    notes[row["key"]] = row["note"]

    def build(name: str, scene_lines: list[SceneLine]) -> str:
        situation = re.sub(r"^[A-Z]+?_(DIALOGUE_)?", "", name.split("#")[0])
        sheet = next((sheets[k] for k in sorted(sheets, key=len, reverse=True) if situation.startswith(k)), "")
        note = next((notes[ln.key] for ln in scene_lines if ln.key in notes), "")
        used = sorted({ln.expression for ln in scene_lines if ln.voiced and ln.expression in meanings})
        parts = [name]
        if sheet:
            parts.append(f"Physical situation: {sheet}")
        if note:
            parts.append(f"Translators' note: {note}")
        if used:
            parts.append("Expression meanings:\n" + "\n".join(f"- {e}: {meanings[e]}" for e in used))
        return "\n\n".join(parts)
    return build


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
    source = lines.read_export(args.lines, profile)
    todo = [(name, sl) for name, sl in _scenes(source, args.only)
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
                           d.api_key_env, context_length=d.context_length)
    context = _scene_context_builder(profile.folder, args.notes)
    work = cfg.path(cfg.paths.work_dir)
    voiced_total = sum(1 for _, sl in todo for ln in sl if ln.voiced)
    st = {"running": True, "host": host, "addresses": sorted(director_status.host_addresses(host)), "model": d.model,
          "scenes_total": len(todo), "scenes_done": 0, "lines_total": voiced_total, "lines_done": 0, "failed": 0,
          "current": "", "started": time.time(), "render": bool(args.render), "phase": "directing"}
    director_status.write(work, st)
    if args.render:  # lines directed in an earlier, interrupted run go to the render queue right away
        _queue_directed(cfg, profile, source, done, {ln.key for _, sl in _scenes(source, args.only) for ln in sl})
    failed: list[tuple[str, list[SceneLine]]] = []
    try:
        for attempt, scenes in enumerate((todo, None)):
            if attempt:  # one more try for the scenes that failed (a busy or restarted server)
                scenes, failed = failed, []
                if scenes:
                    _log.info("retrying %d failed scene(s)", len(scenes))
            for name, scene_lines in scenes:
                st["current"] = name
                director_status.write(work, st)
                try:
                    new = director.direct(context(name, scene_lines), scene_lines)
                    done.update(new)
                    directions.save(out, done)
                    st["scenes_done"] += 1
                    st["lines_done"] += len(new)
                    _log.info("[%d/%d] %s: directed", st["scenes_done"], len(todo), name)
                    if args.render:
                        _queue_directed(cfg, profile, source, done, set(new))
                except (ApiDirectorError, OSError, KeyError, ValueError) as e:
                    failed.append((name, scene_lines))
                    _log.warning("%s: %s", name, e)
                st["failed"] = len(failed)
    finally:
        director.unload()
        st.update(running=False, current="", phase="done", finished=time.time())
        director_status.write(work, st)
    _log.info("directions saved to %s (%d line(s)); %d scene(s) failed – run again to retry them; the model was "
              "unloaded, the worker on that PC renders again", out, len(done), len(failed))
    return 0 if not failed else 1


def _queue_directed(cfg: Config, profile, source: list[lines.SourceLine], directed: dict[str, dict],
                    keys: set[str]) -> None:
    """Queue the directed lines among `keys` for rendering (lines that already have a voice file are skipped)."""
    picked = [s for s in source if s.key in keys and s.key in directed]
    if not picked:
        return
    engine, lang = cfg.render.engine, cfg.render.language
    folder = cfg.path(cfg.paths.work_dir) / "coordinator"
    result = build.build(profile, picked, engine, directed, AssetStore(folder / "assets").add, "",
                         cfg.render.characters, lang)
    output_root = cfg.path(cfg.paths.output_dir)
    todo = [ln for ln in result.lines if not _has_output(output_root, lang, ln)]
    if todo:
        queue = JobQueue(folder / "queue.sqlite", max_attempts=cfg.checks.max_attempts)
        # again=True: a line queued before (without or with an older direction) gets the new direction; lines
        # with a voice file were filtered out above, lines rendering right now are left alone by the queue
        queue.add(engine, todo, again=True)
        queue.close()


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


REFERENCE_KEY = "REFERENCE_TEXT"


def reference(cfg: Config, args: argparse.Namespace) -> int:
    """`crucible reference`: every character reads the profile's reference_text.txt with Chatterbox (queued like any
    line, so the checks and the watcher's Redo apply); `--install` copies the finished readings into the profile as
    the Breeze reference voices (voices/reference/<name>.wav, older files kept as .bak.wav)."""
    from voicecrucible.core import audio
    from voicecrucible.core.jobs import Line
    from voicecrucible.textprep import prepare
    folder = profile_dir(cfg)
    profile = profile_mod.load(folder)
    if not profile.reference_text:
        _log.error("the profile has no reference_text.txt – write a ~70-word, varied text there (see docs/PROFILES.md)")
        return 1
    wanted = set(cfg.render.characters or [])
    chars = [c for c in profile.characters.values() if not wanted or c.folder in wanted]
    output_root, lang = cfg.path(cfg.paths.output_dir), cfg.render.language
    if args.install:
        installed = 0
        for c in chars:
            src = next((p for ext in results.AUDIO_EXTENSIONS
                        if (p := output_root / "voices" / lang / c.folder / f"{REFERENCE_KEY}.{ext}").exists()), None)
            if src is None:
                _log.warning("%s: no finished reading yet (%s)", c.name, output_root / "voices" / lang / c.folder)
                continue
            target = folder / "voices" / "reference" / f"{c.name}.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.replace(target.with_suffix(".bak.wav"))
            y, sr = audio.decode(src.read_bytes())
            target.write_bytes(audio.encode(y, sr, "wav"))
            _log.info("%s: %s -> %s", c.name, src.name, target)
            installed += 1
        _log.info("%d reference voice(s) installed; the 'breeze' engine uses them from now on", installed)
        return 0 if installed else 1
    work = cfg.path(cfg.paths.work_dir) / "coordinator"
    store = AssetStore(work / "assets")
    todo = []
    for c in chars:
        ref = profile.voice(c.name, "chatterbox")
        if ref is None or not ref.exists():
            _log.warning("%s: no Chatterbox voice – skipped", c.name)
            continue
        todo.append(Line(key=REFERENCE_KEY, character=c.folder, text=prepare(profile.reference_text, profile.lexicon),
                         emotion="Neutral", voice=store.add(ref),
                         params=emotions.chatterbox(profile, c.name, "Neutral")))
    queue = JobQueue(work / "queue.sqlite", max_attempts=cfg.checks.max_attempts)
    added = queue.add("chatterbox", todo, again=True)
    queue.close()
    _log.info("%d reading(s) of the reference text queued (Chatterbox). Listen in the watcher (Finished lines, Redo "
              "if needed), then run: crucible reference --install", added)
    return 0
