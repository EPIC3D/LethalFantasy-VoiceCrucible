"""Primed retakes: a line that failed is spoken again as "Okay... <line>", then "Okay" and the pause are cut off.
Doubled retakes: one- and two-word lines ("Squish!", "Stand back!") are spoken twice and the second one is cut off –
alone they are too short for the engine (heard "Help! Insider to clode." for "Stomp!").

Chatterbox often garbles the first word of a take; a short, well known word in front takes the garble. Measured on
Red's lines: 9/24 good starts plain, 18/24 primed (cut at a pause), more with the cut at Whisper's word timing.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from voicecrucible.core.jobs import Line

PRIMER = "Okay..."
MIN_WORDS = 3  # shorter lines are retaken without the primer ...
MAX_DOUBLE_WORDS = 2  # ... but doubled


def wants_primer(line: Line) -> bool:
    """Retakes (attempt 2+) of lines with at least three words; not the last-take fallback phrase of a hum. Very
    short exclamations ("Oof!", "Not again") run into the primer ("Okay-oof") and cannot be cut off cleanly."""
    from voicecrucible.checks.words import words
    return line.attempt > 1 and len(words(line.text)) >= MIN_WORDS and not (
        line.params.get("last_take_text") and (line.attempt - 1) % 3 == 2)


def primed(line: Line) -> Line:
    """The same line with the primer in front of what the engine says."""
    from voicecrucible.engines.base import spoken_text
    return dataclasses.replace(line, params={**line.params, "spoken_text": f"{PRIMER} {spoken_text(line)}"})


def wants_double(line: Line) -> bool:
    """Retakes (attempt 2+) of one- and two-word lines with words; not hums (they have their own fallbacks)."""
    from voicecrucible.checks.words import words
    return line.attempt > 1 and 0 < len(words(line.text)) <= MAX_DOUBLE_WORDS and not line.params.get("last_take_text")


def doubled(line: Line) -> Line:
    """The same line spoken twice ("Squish! Squish!")."""
    from voicecrucible.engines.base import spoken_text
    said = spoken_text(line)
    return dataclasses.replace(line, params={**line.params, "spoken_text": f"{said} {said}"})


def double_cut(y: np.ndarray, sr: int, word_times: list[dict] | None, words_once: int) -> int | None:
    """Sample where the second time starts: between the last word of the first time and the next one (Whisper
    timing), else the first pause after some sound. None when no cut can be found."""
    if word_times and len(word_times) > words_once:
        return int((word_times[words_once - 1]["end"] + word_times[words_once]["start"]) / 2 * sr)
    return _first_pause(y, sr)


def cut_point(y: np.ndarray, sr: int, word_times: list[dict] | None) -> int | None:
    """Sample where the line starts after the primer: between "okay" and the next word (Whisper timing), else the
    middle of the first pause after some sound. None when no cut can be found."""
    if word_times and len(word_times) > 1 and word_times[0]["word"].strip(" ,.!?").lower().startswith("ok"):
        return int((word_times[0]["end"] + word_times[1]["start"]) / 2 * sr)
    return _first_pause(y, sr)


def _first_pause(y: np.ndarray, sr: int) -> int | None:
    """The middle of the first pause (120 ms or longer) after some sound, or None."""
    hop = max(1, int(sr * 0.01))
    n = len(y) // hop
    if n < 3:
        return None
    rms = np.sqrt((y[: n * hop].astype(np.float64).reshape(n, hop) ** 2).mean(axis=1))
    quiet = rms < 0.02 * (rms.max() or 1)
    seen, run = False, 0
    for i, q in enumerate(quiet):
        if not q:
            seen, run = True, 0
        elif seen:
            run += 1
            if run >= 12:  # a pause of 120 ms
                j = i
                while j < n and quiet[j]:
                    j += 1
                return ((i - run + 1 + j) // 2) * hop
    return None
