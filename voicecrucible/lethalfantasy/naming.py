"""Player identity variants: lines with {they}/{them}/{they're} get one file per identity (KEY__he/she/they).

The plugin picks the file that matches the player's chosen identity.
"""

from __future__ import annotations

_IDENT = {
    "he": {"{they}": "he", "{They}": "He", "{them}": "him", "{Them}": "Him", "{they're}": "he's", "{They're}": "He's"},
    "she": {"{they}": "she", "{They}": "She", "{them}": "her", "{Them}": "Her", "{they're}": "she's",
            "{They're}": "She's"},
    "they": {"{they}": "they", "{They}": "They", "{them}": "them", "{Them}": "Them", "{they're}": "they're",
             "{They're}": "They're"},
}


def variants(text: str) -> list[tuple[str, str]]:
    """[(variant, text)]: [("", text)] for normal lines, three entries for identity lines."""
    if "{" not in text:
        return [("", text)]
    out = []
    for name, table in _IDENT.items():
        t = text
        for placeholder in sorted(table, key=len, reverse=True):
            t = t.replace(placeholder, table[placeholder])
        out.append((name, t))
    return out
