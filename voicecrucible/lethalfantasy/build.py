"""Turn the game's lines into queue lines: filter, identity variants, speakable text, voice, engine settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from voicecrucible.checks.words import speechless, words
from voicecrucible.core import languages
from voicecrucible.core.jobs import Line
from voicecrucible.lethalfantasy import emotions, filters, naming
from voicecrucible.lethalfantasy.lines import SourceLine
from voicecrucible.lethalfantasy.profile import Profile
from voicecrucible.textprep import has_words, prepare


@dataclass
class BuildResult:
    """Queue lines plus what was skipped and why (shown to the user)."""

    lines: list[Line] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    missing_voices: set[str] = field(default_factory=set)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def reference_voice(profile: Profile, character: str, engine: str) -> Path | None:
    """The engine's reference voice of a character, else the Chatterbox one (used for the similarity check).
    Breeze has no fallback: its reference must say the profile's reference_text word for word."""
    if engine == "breeze":
        return profile.voice(character, engine) if profile.reference_text else None
    return profile.voice(character, engine) or profile.voice(character, "chatterbox")


def build(profile: Profile, source: list[SourceLine], engine: str, directions: dict[str, dict],
          add_asset: Callable[[Path], str], only: str = "", characters: list[str] | None = None,
          language: str = "en") -> BuildResult:
    """Queue lines for `engine`. `add_asset` stores a reference voice and returns its ID."""
    result = BuildResult()
    engine_language = {"language": languages.qwen_name(language)} if engine in ("qwen", "qwen_vc") else {}
    asset_ids: dict[Path, str] = {}
    wanted = set(characters or [])
    for src in source:
        ch = profile.characters[src.character]
        if only and not src.key.startswith(only):
            continue
        if wanted and ch.folder not in wanted:
            result.skip("character not selected")
            continue
        if not filters.is_voiced(src):
            result.skip("never voiced (player choice / narration)")
            continue
        ref = reference_voice(profile, src.character, engine)
        if ref is None or not ref.exists():
            result.missing_voices.add(src.character)
            result.skip(f"no reference voice for {src.character}")
            continue
        if ref not in asset_ids:
            asset_ids[ref] = add_asset(ref)
        params = {**emotions.params(engine, profile, src.character, src.expression, directions.get(src.key)),
                  **engine_language}
        for variant, text in naming.variants(src.text):
            spoken = prepare(text, profile.lexicon, language=language)
            if not has_words(spoken):
                result.skip("nothing to speak (only symbols)")
                continue
            line_params = params
            if language == "en" and (say := profile.sounds.find(spoken, src.expression)) and speechless(spoken):
                line_params = {**params, "last_take_text": say}  # a hum or a laugh: its last take says this
            voice = asset_ids.get(ref, "")
            if engine == "breeze" and len(words(spoken)) <= emotions.BREEZE_SHORT_WORDS:
                # short lines (up to 5 words): a short instruction and a short reference – with the long ones Breeze
                # spoke parts of them after the word (heard: the reference text, made-up words)
                line_params = {**line_params, "instruction": emotions.breeze_short_instruction(
                    profile, src.expression, directions.get(src.key))}
                short = ref.with_name(ref.stem + ".short" + ref.suffix)
                if short.exists() and profile.reference_text_short:
                    if short not in asset_ids:
                        asset_ids[short] = add_asset(short)
                    voice, line_params = asset_ids[short], {**line_params, "ref_text": profile.reference_text_short}
            result.lines.append(Line(key=src.key, character=ch.folder, text=spoken, emotion=src.expression,
                                     direction=directions.get(src.key, {}).get("delivery", ""), variant=variant,
                                     voice=voice, params=line_params))
    return result
