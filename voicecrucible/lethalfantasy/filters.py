"""What is never voiced: the player's answer choices (_Q) and narration (_S keys, StoryPoise lines)."""

from __future__ import annotations

import re

from voicecrucible.lethalfantasy.lines import SourceLine

_NEVER_KEY = re.compile(r"_(Q|S)(_|$)")  # _Q = player's question/choice, _S = narration
# texts with a character's key prefix that nobody speaks (not in the game's dialogue events): reward notices
# ("Received caretaker's charm"), the affection title words put into other lines ({C}/{L}: "Maiden", "mommy"),
# minigame buttons ("Return", "Step", "Talk"), the player's requests there ("Can you step on me?", "Harder?") and
# the player's choices in the nightgown event ("Yes", "Keep staring")
_NOT_SPOKEN = re.compile(r"_PET_RESPONSE_REWARD_[A-Z]+$|_DIALOGUE_TITLE_[A-Z]+_[CL]$"
                         r"|_FMASSAGE_MINIGAME_(RETURN|STEP|TALK|STOP|STEP_MORE|STEP_MORE_MORE|STEP_HARDER|STEP_HARDER_MORE)$"
                         r"|_NIGHTGOWN_CHOICE_\d+$")


def is_voiced(line: SourceLine) -> bool:
    """True when a character speaks this line aloud."""
    return not _NEVER_KEY.search(line.key) and not _NOT_SPOKEN.search(line.key) and line.type != "StoryPoise"
