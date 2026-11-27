"""Whisper check: were the words spoken, is the first word there (no clipped start), are the names right?

Settings: whisper_model ("small"), min_text_match (0.75), names ({respelling: name prefix}), whisper_prompt.
"""

from __future__ import annotations

import difflib
import re

import numpy as np

from voicecrucible.checks.base import Candidate, Check
from voicecrucible.core.jobs import CheckResult

# interjections the game and Whisper spell freely (hmm, ugh, aww, mm-hmm …): ignored when comparing
_FILLER = re.compile(r"^(h+[aeiou]+h*)+$|^(a+h+|o+h+|u+h+|u*m+|h+m+|e+h+|e+r+|ah|oh)$"
                     r"|^o+h*$|^a+w+$|^g+h?a+h*$|^u+g+h+$|^m+[- ]?h*m+$|^m+hm+$|^mm+hmm+$|^e+p+$|^p+f+t+$|^t+s+k+$"
                     r"|^h+m+p*h*$|^w+h?o+a+h*$")
_EQUIV = {"cause": "because", "'cause": "because", "cuz": "because", "ya": "you", "yeah": "yes",
          "gez": "jez", "gese": "jez", "jese": "jez"}  # Jeez = Geez (after letter merging: "jez")


def _merge(word: str) -> str:
    """'sooo' -> 'so', 'orrnehlla' -> 'ornehla' – also used for the name table, so both sides match."""
    return re.sub(r"(.)\1+", r"\1", word)


def words(text: str) -> list[str]:
    """Normalised words without fillers. Repeated letters are merged (a drawn-out "Soo"/"Sooo" = "so"); this is
    done on both sides of a comparison, so "too" or "good" still match themselves. Apostrophes at a word's edge are
    quote marks ("it's 'be bigger'"), not part of the word; inside a word ("it's") they stay."""
    raw = re.findall(r"[\w']+", text.lower().replace("’", "'").replace("‘", "'"))
    found = (_merge(_EQUIV.get(w, w.strip("'"))) for w in raw if w.strip("'"))
    return [_EQUIV.get(w, w) for w in found if not _FILLER.match(w)]  # any script


def compare(expected: str, heard: str, names: dict[str, str]) -> dict:
    """Match ratio, first-word and names checks between the spoken text and what Whisper heard."""
    names = {_merge(k): _merge(v) for k, v in names.items()}  # the same letter merging as words()
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
    # ... but not a left-over "Okay" of a primed retake whose cut missed it (heard: "Okay, not again" for "Not again")
    inserted_ok = (bool(a) and len(b) > 1 and b[1][:2] == a[0][:2] and len(b) >= len(a)
                   and not (b[0] in ("okay", "ok") and a[0] not in ("okay", "ok")))
    expected_words = set(words(expected))  # whole words: 'lahna' (Lana) must not match inside 'solahna'
    names_ok = all(any(w.startswith(prefix) for w in b) for spelled, prefix in names.items()
                   if spelled in expected_words)
    return {"ratio": ratio, "first_ok": first_ok or inserted_ok, "names_ok": names_ok}


def line_prompt(all_names: str, expected: str, names: dict[str, str]) -> str:
    """Whisper's spelling hint for one line: only the names this line speaks. With every name in the hint, Whisper
    wrote a well spoken "Solahna" as "Selena" (both names were offered); a line without names gets no hint."""
    spoken = {names.get(w, w) for w in words(expected)} | set(words(expected))
    picked = [n for n in (x.strip(" .") for x in all_names.split(",")) if n
              and any(w.startswith(_merge(n.lower())[:3]) for w in spoken)]
    return ", ".join(picked) + "." if picked else ""


SHORT_LINE_WORDS = 4   # lines this short ...
SHORT_LINE_MATCH = 0.9  # ... need almost every word right: an added or missing word fails


class WordsCheck(Check):
    """Speech recognition against the expected text."""

    name = "words"

    def load(self, device: str) -> None:
        import whisper
        self._fp16 = device == "cuda"
        self._model = whisper.load_model(self.settings.get("whisper_model", "small"), device=device)

    def word_times(self, samples: np.ndarray, sample_rate: int) -> list[dict]:
        """[{word, start, end}] in seconds, from Whisper."""
        import librosa
        y16 = librosa.resample(samples.astype(np.float32), orig_sr=sample_rate, target_sr=16000)
        res = self._model.transcribe(y16, language=self.settings.get("language", "en"), fp16=self._fp16,
                                     word_timestamps=True)
        return [{"word": w["word"], "start": w["start"], "end": w["end"]} for s in res["segments"] for w in s["words"]]

    def run(self, take: Candidate) -> CheckResult:
        # a one-round text from the watcher's Redo is what should be heard (free text, or "Sooo" for "So")
        expected = str(take.line.params.get("spoken_text") or take.line.text)
        prompt = line_prompt(str(self.settings.get("whisper_prompt") or ""), expected, self.settings.get("names", {}))
        heard = self._model.transcribe(take.audio16k, language=self.settings.get("language", "en"), fp16=self._fp16,
                                       initial_prompt=prompt or None)["text"].strip()
        r = compare(expected, heard, self.settings.get("names", {}))
        say = str(take.line.params.get("last_take_text", ""))
        if say and r["ratio"] < 1.0:  # a hum's fallback take ("Yes.") is right too
            r = max(r, compare(say, heard, self.settings.get("names", {})), key=lambda x: x["ratio"])
        problems = []
        limit = self.settings.get("min_text_match", 0.75)
        if 0 < len(words(expected)) <= SHORT_LINE_WORDS:  # one extra word is a real fault in a short line
            limit = max(limit, SHORT_LINE_MATCH)               # (heard: "Get up them, Lena" passed with 0.86)
        if r["ratio"] < limit:
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
