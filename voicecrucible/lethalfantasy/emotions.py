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


ENERGY_STEP = 0.08  # exaggeration per energy step away from 3 (1..5 -> -0.16..+0.16)
PACE_STEP = {"slow": -0.07, "normal": 0.0, "fast": 0.07}  # cfg_weight: lower = slower, more deliberate


def chatterbox(profile: Profile, character: str, expression: str, direction: dict | None = None) -> dict:
    """Chatterbox sliders for a character and expression; a direction's energy (1-5, 3 = usual for this expression)
    and pace nudge them in a narrow band around the user-tested table."""
    table = profile.emotions["chatterbox"]
    e, c = table.get(expression, table["Neutral"])
    de, dc = profile.characters[character].chatterbox_adjust
    if expression in profile.emotions["strong"] and de < 0:
        de = 0.0
    if direction:
        m = re.search(r"[1-5]", str(direction.get("energy", "")))
        de += (int(m.group(0)) - 3) * ENERGY_STEP if m else 0.0
        dc += PACE_STEP.get(str(direction.get("pace", "")).strip().lower(), 0.0)
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


BREEZE_DEFAULTS = {"cfg_scale": 3.25,  # the suffix asks for the reference's accent: heard it drift on longer lines
                   "suffix": "Adult woman, never childlike or squeaky. "
                             "Keep exactly the same English accent as the reference voice."}
# Breeze's own voice-match thresholds (good Breeze takes measured 0.74-0.95; one at 0.61 was another speaker)
BREEZE_CHECKS = {"check_min_similarity": 0.72, "check_intense_min_similarity": 0.65}


def breeze(profile: Profile, character: str, expression: str, direction: dict | None) -> dict:
    """Breeze Voice Direction: the long acting instruction (scene, intent, subtext, expression meaning, delivery,
    pace, avoid) – it clearly beat a short one in the 2026-11-25 listening test – plus cfg_scale and the reference
    transcript. Without a direction the expression and its meaning steer the line."""
    b = {**BREEZE_DEFAULTS, **profile.emotions.get("breeze", {})}
    meaning = profile.expressions.get(expression, "")
    face = f"Facial expression: {expression}" + (f" ({meaning})" if meaning else "") + "."
    if direction:
        d = {k: str(direction.get(k, "")).strip() for k in ("scene", "intent", "subtext", "delivery", "pace", "avoid")}
        text = (f"{d['scene']} Intent: {d['intent']} Subtext: {d['subtext']} {face} "
                f"Delivery: {sanitize(d['delivery'], profile)}" + (f", pace {d['pace']}" if d["pace"] else "") +
                f". Avoid: {d['avoid']}.")
    else:
        text = face
    return {"instruction": f"{text} {b['suffix']}".strip(), "cfg_scale": float(b["cfg_scale"]),
            "ref_text": profile.reference_text, **BREEZE_CHECKS}


BREEZE_SHORT_WORDS = 5  # lines this short get a short instruction and reference (heard leaks up to 3 words)
BREEZE_STRENGTH = {  # the direction's energy (1-5), said outright in a short instruction
    "5": "Fully acted with very strong emotion: loud, intense, not calm at all.",
    "4": "Clearly acted with strong emotion, not calm.",
    "2": "Restrained and soft.",
    "1": "Very soft, almost a whisper.",
}


def breeze_short_instruction(profile: Profile, expression: str, direction: dict | None) -> str:
    """For short lines ("Squish!", "Watch my feet!"): only how it sounds. With the long instruction Breeze spoke
    parts of it after the word, in a made-up language (heard: "Squish. So dear she like Dara's ..."). Without the
    scene the strength must be said outright (heard: Blue's "You need to run!" flat and calm)."""
    b = {**BREEZE_DEFAULTS, **profile.emotions.get("breeze", {})}
    d = {k: str((direction or {}).get(k, "")).strip() for k in ("delivery", "avoid", "energy", "pace")}
    parts = [f"A short {expression.lower()} line, spoken in English, only these words and nothing else."]
    strength = BREEZE_STRENGTH.get(d["energy"], "")
    if strength:
        parts.append(strength)
    if d["delivery"]:
        parts.append(f"Delivery: {sanitize(d['delivery'], profile)}" + (f", {d['pace']} pace" if d["pace"] else "") + ".")
    if d["avoid"]:
        parts.append(f"Avoid: {d['avoid']}.")
    return " ".join(parts + [b["suffix"]])


def params(engine: str, profile: Profile, character: str, expression: str, direction: dict | None) -> dict:
    """Engine settings for one line."""
    if engine == "chatterbox":
        return chatterbox(profile, character, expression, direction)
    if engine in ("qwen", "qwen_vc"):
        return qwen(profile, character, expression, direction)
    if engine == "breeze":
        return breeze(profile, character, expression, direction)
    return {}
