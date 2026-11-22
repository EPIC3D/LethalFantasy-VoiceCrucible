# Profiles

A **profile** holds everything about the characters you render: who speaks, their reference voices, how each
game expression is acted, how names are pronounced, and the brief for an AI director.

```mermaid
flowchart LR
    D[profiles\lethalfantasy\<br/>bundled default – ready to use] --> R[crucible render]
    D -->|profile new my-voices --from lethalfantasy| C[profiles\my-voices\<br/>your editable copy]
    T[profiles\template\<br/>empty start] -->|profile new my-voices| C
    S[A profile zip from someone] -->|profile install| C
    C -->|"[render] profile = my-voices"| R
```

## The bundled default: `lethalfantasy`

Voice Crucible comes with a ready profile – **the voices and settings of the LethalFantasy TTS demo**:
Chatterbox reference voices for Akipo, Red and Blue, the tuned emotion table, expression meanings and name
pronunciation. No acting director (no character descriptions, no acting references). It is the default
(`[render] profile = "lethalfantasy"`), so rendering works right after setup.

It is **part of the program**: every Voice Crucible update replaces it with the maintainer's current version.
Don't edit it – make a copy instead. If you did change it anyway, the update first saves your version to
`profiles\lethalfantasy.backup-<date>\` (the same for `template\`), so nothing is lost.

## Your own profile

**In the watcher** (easiest):

- **Profiles** panel: **Use** switches the active profile (remembered, no config edit), **Make my own copy**,
  **Import profile…** (a shared profile zip), **Open folder** (edit the files by hand).
- **Voices** panel: listen to each character's reference clip; **Replace…** takes a clip you choose (5–30 s of
  clean speech of one voice, no music; wav, flac, ogg or mp3) and makes it that character's reference voice. The
  old clip is kept as `<name>.bak.wav`. On the bundled profile it first makes your own copy and switches to it,
  because program updates replace the bundled one.

**On the command line:**

- **Copy the default and change it:** `crucible.cmd profile new my-voices --from lethalfantasy`
- **Start empty:** `crucible.cmd profile new my-voices` (from the template; the speakers are added from the
  game export when you run `render --dry-run`, voice pack folders come from `plugin_folders.json`)
- **Install a profile someone shared:** `crucible.cmd profile install <zip>`

Then set `[render] profile = "my-voices"` in `voicecrucible.toml`. Updates never touch your own profiles.
`crucible.cmd profile list` shows all profiles (`*` = active).

### What to change

1. **Voices** – put one reference clip per character into `voices\chatterbox\` (and `voices\acting\` for
   acting packs): 10–25 seconds of clean speech, WAV/FLAC/OGG, named as in `characters.json`. Any voice works,
   also a male one. Only use voices you have the right to use.
2. `characters.json` – per speaker: `folder` (the plugin's voice pack folder, LethalFantasy: `AKIPO`, `RED`,
   `BLUE`), `voices`, `chatterbox_adjust`, and for the acting engines `bible` / `persona` (voice and
   personality).
3. Optional: `pronunciation.json`, `emotions.json`, `expressions.json`, `director_brief.md` – each file has
   comments.

A speaker added in a later game version is added to your profile automatically and skipped until it has a
reference clip.

## What is in a profile

| File | What it holds |
|---|---|
| `profile.json` | name, title, version |
| `characters.json` | speakers: voice pack folder, key prefix, reference clip per engine, acting description, Chatterbox adjustment |
| `plugin_folders.json` | game speaker ID → the plugin's voice pack folder (used when speakers are added automatically) |
| `voices\` | reference clips; optional `skip_sound.wav` (or .ogg/.mp3/.flac): played for lines you skip in the watcher instead of silence – e.g. crickets. Not bundled: use a sound whose licence allows your use. |
| `emotions.json` | game expression → engine settings (Chatterbox sliders, Qwen styles), words replaced in directions |
| `expressions.json` | what each game expression means for the acting |
| `pronunciation.json` | name respellings for the engines (subtitles stay unchanged) |
| `sound_fallbacks.json` | optional: for lines without words (a hum, a laugh, a sigh) – what the last take says if the engine cannot make the sound, e.g. "Mm-hmm" → "Yes.", "Hehe…" → "That is funny!", "Ahhh" with a happy expression → "Feels good…". Rules match the sound, optionally the ending (`?`) and the game's expression. English packs only. |
| `director_brief.md` | instructions and character notes for an AI director |

## Re-rendering after a change

Lines that were already rendered stay as they are. To render them again, delete their files from `output\`
(or the whole character folder) and run `render` again – lines already in the queue are not queued twice.

## Sharing a profile

Zip the profile folder itself (one folder with `profile.json` inside). Others install it with
`crucible.cmd profile install <zip>`; an existing profile of the same name is first copied to
`profiles\<name>.backup-<date>\`. Only share voices and texts you are allowed to share.
