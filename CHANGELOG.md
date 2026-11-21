# Changelog

## 0.1.0b6 – unreleased

- **Watcher:** Pause/Resume rendering; per worker Stop (standby), Resume and Shutdown – each asks first and is only
  offered to workers that support it; "Unpair" moved to the pairing panel; current batch per worker (engine,
  lines done, current line); Output panel (pack folder, files per character, report, logs); says whether a
  worker is older or newer than the coordinator; for an offline worker it says why (e.g. "missing component –
  run setup.cmd on that PC", "shut down from the watcher", or "no contact since 20:39").
- **Memory Orb audiobook (story mode):** `crucible story --lines <export>` renders the pages (narrator, the
  Twins' coloured lines in their own voices), `--join` builds `voices/<language>/STORY/<page>.ogg`. The default
  profile has a narrator voice.
- Fix: writing long OGG files crashed the program (libsndfile) – written in blocks now.
- Fix: a worker restarted after "Shutdown" works again right away.
- Security: Pillow 13 (all critical Dependabot warnings), diffusers 0.38; Seed-VC installs fewer packages
  (no gradio, fastapi, starlette, modelscope, ...) and uses transformers 4.57.3. Remaining warnings are
  explained in docs/SECURITY.md.
- Window titles for the launchers ("Voice Crucible - worker", ...); `.cmd` files always with Windows line ends.

## 0.1.0b5 – 2026-11-21

Tested on Windows 11 with NVIDIA RTX 40 and RTX 50 series cards (incl. a worker updating itself from b1 to b4
via the watcher), against LethalFantasy beta 1.0.3.

- **Fix: running `setup.cmd` again could remove installed components** (PyTorch, Chatterbox, ...) if it did
  not run to the end. Its first step no longer removes anything.
- After an update, packages that the new version needs for your installed components are added automatically.
- A worker with a missing component gives its job back without using up the lines' attempts, stops and says
  "run setup.cmd".
- `crucible.cmd render --retry-failed` queues lines that failed for good again.

## 0.1.0b4 – 2026-11-21

(0.1.0b3 was tagged but never released; its changes are part of this version.)

Tested on Windows 11 with NVIDIA RTX 40 and RTX 50 series cards, against LethalFantasy beta 1.0.3.

- **Bundled default profile `lethalfantasy`:** the voices and settings of the LethalFantasy TTS demo
  (Chatterbox reference voices, emotion table, expressions, pronunciation; no acting director). Rendering
  works right after setup. Program updates refresh it; your own profiles are never touched.
- `crucible profile new <name> --from lethalfantasy` makes an editable copy; without `--from` it starts
  empty from the template.
- **Extending a pack:** `render` skips lines that already have a voice file, so after a game update only the
  new lines are rendered (`--all` renders everything again).
- **Lines that fail every check still get a file:** the best take (highest audio quality) is exported and
  marked in `report.tsv` as "failed – best take used", like the original voice pack pipeline.
- **Updates keep your changes to the bundled profiles:** if `profiles\lethalfantasy\` or `template\` was
  edited, it is saved to `profiles\<name>.backup-<date>\` before the update replaces it.
- FAQ: where the lines come from (your game's export) and what Weblate is used for.

## 0.1.0b2 – 2026-11-21

Tested on Windows 11 with NVIDIA RTX 40 and RTX 50 series cards, against LethalFantasy beta 1.0.3.

- **Profiles: make your own from the template** – `crucible profile new lethalfantasy`, then
  `render --dry-run` adds the game's speakers (voice pack folders from `plugin_folders.json`: AKIPO, RED,
  BLUE) and tells you where each reference clip goes. No profile pack download is needed
  (see docs/PROFILES.md).
- Without a `voicecrucible.toml`, the `work`, `output` and `logs` folders are always created in the Voice
  Crucible folder (0.1.0b1 created them in the folder the command was started from).
- README: how-it-works diagram, link to the LethalFantasy TTS plugin, support section; the Memory Orb
  audiobook is not part of Voice Crucible (yet).
- Update check: GitHub tags (`v0.1.0-beta.2`) are compared with the program version (`0.1.0b2`) correctly.
  In 0.1.0b1 `crucible update` offers the same version again and then refuses it (harmless).
- Workers asked to update while already on the latest version report "up to date" instead of an error.

## 0.1.0b1 – 2026-11-21 (first beta)

Tested on Windows 11 with NVIDIA RTX 40 and RTX 50 series cards, against LethalFantasy beta 1.0.3.

- Coordinator + any number of workers on the local network: pairing code, TLS with pinned certificate,
  discovery (DHCP-safe), leases (lines of a lost worker go back to the queue), watcher web page.
- Engines: Chatterbox (default packs), Qwen3-TTS, Qwen3-TTS + Seed-VC (acting packs; Seed-VC runs as a
  separate GPL program).
- Quality checks on every take: words (Whisper), voice match (resemblyzer), audio quality (UTMOS), pitch;
  failed lines are rendered again.
- LethalFantasy profile: reads the plugin's line export, he/she/they variants, never voices player choices or
  narration, new speakers added automatically, any pack language.
- Optional AI director (any OpenAI-compatible API, local or cloud) writing an editable `directions.json`.
- Setup: everything inside the install folder, download list with sources/licenses/sizes shown first, GPU and
  drive checks, `INSTALLED.txt`; `crucible diagnose` for bug reports; signed manual updates with rollback;
  optional update requests from the watcher (workers update themselves, coordinator last).
