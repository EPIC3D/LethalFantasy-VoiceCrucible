# Changelog

## 0.1.0b6 – 2026-11-22

Tested on Windows 11 with an NVIDIA RTX 40 series card (coordinator, watcher and worker on one PC), against
LethalFantasy beta 1.0.3. Stop / Shutdown of remote workers were not tested with this version yet.

- **Watcher as the main window:** a **Render** panel (line export folder with *Browse…*, engine, "only keys
  starting with", line limit, render again, texts file for other languages) with *Check (dry run)*, *Start
  rendering*, *Retry failed lines*, *Report* and the audiobook buttons; the command's output is shown live and the
  last form values are remembered. **Start worker on this PC** (pairs this computer automatically the first time,
  opens the worker in its own window). **Voices** panel: listen to every character's reference clip and replace it
  from a file (own profiles; the bundled one is protected). Every button runs the same `crucible.cmd` command – the
  command line stays fully usable. Remote workers are still started on their own PC (no background service).
- **Profiles panel:** every installed profile (version, characters, missing voices); **Use** switches the active
  profile without editing voicecrucible.toml or restarting (remembered for the next start); **Make my own copy**;
  **Import profile…** (a profile pack zip, backup of an older version first); **Open folder** for editing the files.
  New: `crucible render|story --profile <name>` uses another profile for one run.
- Security: the watcher refuses requests with a foreign `Host` header (DNS rebinding).
- **"Setup needed" in the watcher:** setup remembers which package list it installed; when a new version needs
  packages that are not installed yet (e.g. after unzipping it by hand), the watcher shows a banner with **Run setup**
  – it closes this computer's worker and the coordinator (setup replaces files they use) and opens setup in its own
  window; when setup is done it starts the coordinator again and the page reloads by itself. A worker started
  with missing packages says so too.
- Watcher Progress: runtime of the render (kept across coordinator restarts) and the speed of all workers together
  (lines/min).
- Watcher: while a worker loads a model it shows "loading the model…" and the growing size of the model folder
  (the first time the model is downloaded, several GB) instead of "0 / 16 lines".
- Faster first model download: `hf_xet` (Hugging Face's downloader) is installed with Chatterbox and Qwen – it was
  skipped on Windows because of a platform-name check in huggingface-hub. Run `setup.cmd` again to get it.
- **Watcher:** Pause/Resume rendering; per worker Stop (standby), Resume and Shutdown – each asks first and is only
  offered to workers that support it; "Unpair" moved to the pairing panel; current batch per worker (engine,
  lines done, current line); Output panel (pack folder, files per character, report, logs); says whether a
  worker is older or newer than the coordinator; for an offline worker it says why (e.g. "missing component –
  run setup.cmd on that PC", "shut down from the watcher", or "no contact since 20:39").
- **Memory Orb audiobook (story mode):** `crucible story --lines <export>` renders the pages (narrator, the
  Twins' coloured lines in their own voices), `--join` builds `voices/<language>/STORY/<page>.ogg`. The default
  profile has a narrator voice.
- **Your edits are not overwritten:** joining audiobook pages keeps a page file that already exists (`--all` /
  "Render again" replaces it); rendering a line again keeps the previous file. The old file is kept as
  `<name>.bak.ogg` in both cases. Voice Crucible never writes into the game: an `output_dir` or `work_dir` inside
  the game's `BepInEx` folder is refused, so the voices the plugin uses can only be replaced by copying them yourself.
- Fix: writing long OGG files crashed the program (libsndfile) – written in blocks now.
- Fix: a worker restarted after "Shutdown" works again right away.
- Security: Pillow 13 (all critical Dependabot warnings), diffusers 0.38; Seed-VC installs fewer packages
  (no gradio, fastapi, starlette, modelscope, ...) and uses transformers 4.57.3. Remaining warnings are
  explained in docs/SECURITY.md.
- Docs: the plugin's line export is in `<game>\BepInEx\LFTTS-export\` from plugin 0.5.1 on (was
  `BepInEx\LethalFantasyTTS\`) and is written when the first dialogue line appears, not at the main menu.
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
