"""Whisper check: were the words spoken, is the first word there (no clipped start), are the names right?

Settings: whisper_model ("small"), min_text_match (0.75), names ({respelling: name prefix}), whisper_prompt.
"""

from __future__ import annotations

import difflib
import re

from voicecrucible.checks.base import Candidate, Check
from voicecrucible.core.jobs import CheckResult

# interjections the game and Whisper spell freely (hmm, ugh, aww, mm-hmm …): ignored when comparing
_FILLER = re.compile(r"^(h+[aeiou]+h*)+$|^(a+h+|o+h+|u+h+|u*m+|h+m+|e+h+|e+r+|ah|oh)$"
                     r"|^o+h*$|^a+w+$|^g+h?a+h*$|^u+g+h+$|^m+[- ]?h*m+$|^m+hm+$|^mm+hmm+$|^e+p+$|^p+f+t+$|^t+s+k+$"
                     r"|^h+m+p*h*$|^w+h?o+a+h*$")
_EQUIV = {"cause": "because", "'cause": "because", "cuz": "because", "ya": "you", "yeah": "yes"}


def words(text: str) -> list[str]:
    """Normalised words without fillers."""
    return [_EQUIV.get(w, w) for w in re.findall(r"[\w']+", text.lower().replace("’", "'"))  # any script
            if not _FILLER.match(w)]


def compare(expected: str, heard: str, names: dict[str, str]) -> dict:
    """Match ratio, first-word and names checks between the spoken text and what Whisper heard."""
    a = [names.get(w, w) for w in words(expected)]
    # a respelled name became its prefix ('seleena' -> 'sel'): shorten the heard name the same way, so the correctly
    # heard 'selena' matches it (comparing 'sel' with 'selena' failed good takes like "Seleena added.")
    prefixes = {names[w] for w in words(expected) if w in names}
    b = [next((p for p in prefixes if w.startswith(p)), w) for w in words(heard)]
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if not a:  # a hum or a sound: only fillers may be heard (its fallback phrase is checked in WordsCheck.run)
        ratio = 1.0 if not b else 0.0
    first_ok = not a or (bool(b) and b[0][:2] == a[0][:2])
    # engines sometimes add an interjection ("Ugh, ...") before the line: fine if the line follows. It still counts
    # against the match: on a one-word line it is a weak take (heard: "Duh, definitely" for "Definitely")
    inserted_ok = bool(a) and len(b) > 1 and b[1][:2] == a[0][:2] and len(b) >= len(a)
    expected_words = set(words(expected))  # whole words: 'lahna' (Lana) must not match inside 'solahna'
    names_ok = all(any(w.startswith(prefix) for w in b) for spelled, prefix in names.items()
                   if spelled in expected_words)
    return {"ratio": ratio, "first_ok": first_ok or inserted_ok, "names_ok": names_ok}


class WordsCheck(Check):
    """Speech recognition against the expected text."""

    name = "words"

    def load(self, device: str) -> None:
        import whisper
        self._fp16 = device == "cuda"
        self._model = whisper.load_model(self.settings.get("whisper_model", "small"), device=device)

    def run(self, take: Candidate) -> CheckResult:
        heard = self._model.transcribe(take.audio16k, language=self.settings.get("language", "en"), fp16=self._fp16,
                                       initial_prompt=self.settings.get("whisper_prompt") or None)["text"].strip()
        r = compare(take.line.text, heard, self.settings.get("names", {}))
        say = str(take.line.params.get("last_take_text", ""))
        if say and r["ratio"] < 1.0:  # a hum's fallback take ("Yes.") is right too
            r = max(r, compare(say, heard, self.settings.get("names", {})), key=lambda x: x["ratio"])
        problems = []
        if r["ratio"] < self.settings.get("min_text_match", 0.75):
            problems.append(f"words differ ({r['ratio']:.2f})")
        if not r["first_ok"]:
            problems.append("first word missing")
        if not r["names_ok"]:
            problems.append("name not spoken")
        reason = f"{', '.join(problems)} – heard: {heard!r}" if problems else ""
        return CheckResult(self.name, not problems, reason, round(r["ratio"], 3))


CHECK = WordsCheck


def speechless(text: str) -> bool:
    """True for lines without words – only a hum, a laugh or a sound ("Mm-hmm", "Hehehe~", "Ahh!")."""
    return not words(text)
