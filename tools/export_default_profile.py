"""Maintainer tool: copy the maintainer's current profile into the repository as the bundled default profile.

  python tools/export_default_profile.py <source profile folder> [<target>, default profiles/lethalfantasy]

The default profile is the director-free demo setup: Chatterbox reference voices, emotion table, expression
meanings, pronunciation and plugin folders. Left out on purpose (director / acting only): the characters'
`bible` and `persona` texts, the director brief (replaced by the template's generic one) and the acting
reference voices. Run it before every release.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
COPY = ("emotions.json", "expressions.json", "pronunciation.json")


def export(src: Path, dst: Path) -> None:
    """Rebuild `dst` from `src` without the director-only parts."""
    if not (src / "characters.json").exists():
        sys.exit(f"not a profile: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "voices" / "chatterbox").mkdir(parents=True)
    for name in COPY:
        shutil.copyfile(src / name, dst / name)
    shutil.copyfile(ROOT / "profiles" / "template" / "director_brief.md", dst / "director_brief.md")
    plugin_folders = src / "plugin_folders.json"
    shutil.copyfile(plugin_folders if plugin_folders.exists() else ROOT / "profiles" / "template" / "plugin_folders.json",
                    dst / "plugin_folders.json")
    meta = json.loads((src / "profile.json").read_text(encoding="utf-8"))
    meta.update(name="lethalfantasy", title="LethalFantasy – default (Chatterbox demo voices, no director)",
                description="Bundled default profile: the voices and settings of the LethalFantasy TTS demo. "
                            "Updated with Voice Crucible; make a copy (crucible profile new <name> --from "
                            "lethalfantasy) to change it.")
    (dst / "profile.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    chars = json.loads((src / "characters.json").read_text(encoding="utf-8"))
    out = {"_comment": "Bundled default profile – do not edit here (program updates replace it); copy it with "
                       "'crucible profile new <name> --from lethalfantasy'. folder = the plugin's voice pack "
                       "folder; voices = reference clip per engine; chatterbox_adjust = [exaggeration, cfg_weight]."}
    for name, c in chars.items():
        if name.startswith("_"):
            continue
        voice = c.get("voices", {}).get("chatterbox")
        if voice:
            shutil.copyfile(src / voice, dst / voice)
        out[name] = {"folder": c["folder"], "prefix": c["prefix"], "voices": {"chatterbox": voice} if voice else {},
                     "chatterbox_adjust": c.get("chatterbox_adjust", [0.0, 0.0])}
    (dst / "characters.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    story = src / "story.json"
    if story.exists():  # Memory Orb audiobook: settings + its voices (e.g. the narrator)
        shutil.copyfile(story, dst / "story.json")
        for voice in json.loads(story.read_text(encoding="utf-8")).get("voices", {}).values():
            (dst / voice).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / voice, dst / voice)
    print(f"default profile written to {dst}:", ", ".join(sorted(p.name for p in dst.rglob("*") if p.is_file())))


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    export(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) == 3 else ROOT / "profiles" / "lethalfantasy")
