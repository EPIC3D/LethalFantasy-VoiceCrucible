"""Game expression (+ optional acting direction) -> engine settings for one line.

chatterbox: exaggeration / cfg_weight from the user-tested table, nudged per character (extrovert Red,
introvert Blue). qwen / qwen_vc: a VoiceDesign instruction – calm style + character bible for normal lines,
an expressive style without the soothing bible for intense ones (calibration: strong emotions were flat).
"""

from __future__ import annotations

import re

from voicecrucible.lethalfantasy.profile import Profile


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def chatterbox(profile: Profile, character: str, expression: str) -> dict:
    """Chatterbox sliders for a character and expression."""
    table = profile.emotions["chatterbox"]
    e, c = table.get(expression, table["Neutral"])
    de, dc = profile.characters[character].chatterbox_adjust
    if expression in profile.emotions["strong"] and de < 0:
        de = 0.0
    return {"exaggeration": round(_clip(e + de, 0.25, 1.2), 3), "cfg_weight": round(_clip(c + dc, 0.2, 0.7), 3)}


def sanitize(text: str, profile: Profile) -> str:
    """Replace direction words that push the voice childlike/squeaky with adult equivalents."""
    for pattern, replacement in profile.emotions["sanitize"]:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def qwen(profile: Profile, character: str, expression: str, direction: dict | None) -> dict:
    """Qwen VoiceDesign instruction and sampling settings."""
    q = profile.emotions["qwen"]
    meaning = profile.expressions.get(expression, "")
    body = f"Facial expression in the game: {expression}" + (f" ({meaning})." if meaning else ".")
    if direction:
        body = (f"Scene: {direction.get('scene', '')} Intent: {direction.get('intent', '')} "
                f"Subtext: {direction.get('subtext', '')} {body} "
                f"Delivery: {sanitize(direction.get('delivery', ''), profile)}. Avoid: {direction.get('avoid', '')}.")
    ch = profile.characters[character]
    if expression in profile.emotions["intense"]:
        return {"mode": "design", "instruct": f"{q['intense_style']}{ch.persona} {body}", **q["intense_gen"]}
    return {"mode": "design", **q["normal"],
            "instruct": f"{q['style']}{ch.bible} {body} Her own voice stays the same; only the acting changes."}


def params(engine: str, profile: Profile, character: str, expression: str, direction: dict | None) -> dict:
    """Engine settings for one line."""
    if engine == "chatterbox":
        return chatterbox(profile, character, expression)
    if engine in ("qwen", "qwen_vc"):
        return qwen(profile, character, expression, direction)
    return {}
