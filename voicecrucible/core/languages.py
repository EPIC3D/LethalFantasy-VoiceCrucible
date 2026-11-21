"""Voice pack language codes (the plugin's folder names) and what each engine calls the language.

Any folder name works for output; unknown languages simply get no engine hints (Whisper detects them).
"""

from __future__ import annotations

# folder code -> (Whisper code, Qwen3-TTS language name)
_KNOWN = {
    "en": ("en", "English"), "hu": ("hu", None), "ja": ("ja", "Japanese"), "zh": ("zh", "Chinese"),
    "es": ("es", "Spanish"), "fr": ("fr", "French"), "pt-BR": ("pt", "Portuguese"), "ru": ("ru", "Russian"),
    "de": ("de", "German"), "it": ("it", "Italian"), "ko": ("ko", "Korean"),
}
ENGLISH_ONLY_ENGINES = {"chatterbox"}


def whisper_code(language: str) -> str | None:
    """Language hint for Whisper; None = let Whisper detect it."""
    return _KNOWN.get(language, (None, None))[0]


def qwen_name(language: str) -> str | None:
    """Qwen3-TTS language name; None when Qwen does not support the language."""
    return _KNOWN.get(language, (None, None))[1]
