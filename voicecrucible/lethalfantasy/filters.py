"""What is never voiced: the player's answer choices (_Q) and narration (_S keys, StoryPoise lines)."""

from __future__ import annotations

import re

from voicecrucible.lethalfantasy.lines import SourceLine

_NEVER_KEY = re.compile(r"_(Q|S)(_|$)")  # _Q = player's question/choice, _S = narration


def is_voiced(line: SourceLine) -> bool:
    """True when a character speaks this line aloud."""
    return not _NEVER_KEY.search(line.key) and line.type != "StoryPoise"
