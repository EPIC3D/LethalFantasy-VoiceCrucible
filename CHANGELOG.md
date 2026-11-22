# Changelog

## 0.1.0b8 – 2026-11-22

Tested on Windows 11 with an NVIDIA RTX 40 series card (coordinator, watcher and worker on one PC), against
LethalFantasy beta 1.0.3. Updating a remote worker to this version may need one manual start of `worker.cmd`
(see below).

- **Fix: a worker did not start again after updating itself** (seen 0.1.0b6 → 0.1.0b7): the update replaced
  `worker.cmd` while it was running, and Windows then read the rest of the file from the wrong place. The restart
  loop now runs from a temporary copy, and `crucible.cmd` ends on the same line as the program. Start workers
  with `worker.cmd` (not `crucible.cmd worker`) – only it restarts them. Updating to this version may need one
  manual start (the update runs with the old launchers).
- **Watcher: foldable panels** – click a heading to fold a panel to one line with a short summary (workers online,
  active profile, files per folder, the latest problem, ...); remembered in the browser.
- **Watcher: voice pack folder** – "Voice pack (written to)" can be changed in the Render panel (never inside the
  game's BepInEx folder, not while lines are rendering) and is remembered; `render|story|report --output <folder>`.
  The input is now called "Game lines (read from)" so it is not mistaken for a target.
- **Watcher help:** a "?" on every panel explains it (hover) and opens the matching guide on GitHub; Help, FAQ and
  Troubleshooting links at the top.
- **Watcher: Replace… on the bundled profile** makes your own copy first (updates replace the bundled one) and puts
  your clip there; "Show voices for" filters the Voices panel by engine; dark dropdown lists.
- Fix: after an update the watcher page could be newer than the running coordinator (buttons answered "not found",
  fields showed "undefined"); the coordinator now serves the page it started with.
- **Fix: good takes with a respelled name were rejected** – the words check compared the name's short form
  ('sel') with what Whisper heard ('selena'), so "Seleena added." scored 50 %. Short clips (under 2 s) get a
  slightly lower voice-similarity limit (0.72 instead of 0.80): their voice print is unsteady.
- **Watcher: what the export holds** – under "Game lines" the watcher shows the number of texts, dialogue lines
  per speaker and type, and the expressions (emotions) found (hover for each one's count).
- **Fix: "Retry failed lines" rendered exactly the same takes again** (the take number, and with it the seed,
  started at 1 again). A retried line now continues with new takes (take 4, 5, ...).
- **Fix: "Render again" (`--all`) did nothing for lines already in the queue** – they were skipped as "already
  queued". They are now queued once more with their new text and settings (after a pronunciation or profile
  change), with new takes. The audiobook gets "only keys starting with" too (`story --only`).
- Chatterbox: one- and two-word lines ("Mm-hmm", "Definitely") are rendered with calmer settings (exaggeration at
  most 0.5, cfg_weight at least 0.5) – strong emotion settings turned them into noise.
- Interjections the engines read as letters are spelled out: "Mhm" -> "Mm-hmm", "Hm" -> "Hmm", "Uhhuh" ->
  "Uh-huh" (heard: a Twin's "Mhm" came out as noise).
- **Problems: ▶ play** the take of a line that failed a check (the best take so far, or the one exported).
  **Accept** marks it done by hand when the take is fine (it becomes the line's voice file and is not rendered
  again).
  **Skip** leaves a line that cannot be spoken well (e.g. a hum) without a voice: the game shows it silently, the
  audiobook join leaves the part out; an exported take is renamed to `.skipped.ogg`. "Render again" brings it back.
  Optional: put your own `voices\skip_sound.wav` (or .ogg/.mp3/.flac) into the profile – e.g. crickets – and
  skipped lines play it instead of silence. The bundled profile has a 1-second silent placeholder; replace it with
  a sound whose licence allows your use.
- **Lines without words** (a hum, a laugh, a sound: "Mm-hmm", "Hehehe~", "Ahh!"): each retry stretches the sound
  ("Mm-hmm" -> "Mmm-hmmm..." -> "Mmmm-hmmmm...", heard: the quick one came out as noise, the long one sounded
  human); the speech-quality score is not used for them (it rates every hum as poor) and the voice-similarity limit
  is 0.50 (good hums measured 0.52-0.62, noise 0.43).
  If the sound did not work, the last take says a short phrase with the same meaning, from the profile's new
  `sound_fallbacks.json` (editable): "Mm-hmm" -> "Yes.", "Hmm?" -> "Yes?", "Hmm..." -> "I wonder...", "Hehe" ->
  "That is funny!", "Ahhh" with a happy expression -> "Feels good..."; pain or shock gets no phrase. The subtitle
  never changes.
- Interjection spellings and other English-only text rules are used for English packs only.
- **Diagnose button** in the watcher (Output panel): collects the bug report facts of this computer (personal data
  removed), shows them and downloads them as `voicecrucible-diagnose.txt`.

Tested on Windows 11 with NVIDIA RTX 40 and RTX 50 series cards (a remote worker updated itself from 0.1.0b5
to 0.1.0b6 via the watcher), against LethalFantasy beta 1.0.3.

- **Cancel render:** a button in the watcher (and `crucible render --cancel`) removes the waiting and rendering
  lines; workers stop their current batch, finished voice files are kept.
- **An unfinished render no longer starts by itself:** when the coordinator starts with lines left from an earlier
  render, rendering is paused and the watcher asks: Resume or Cancel render.
- Fix: "Setup needed" was shown after every new version, even when no package changed (the check looked at
  Voice Crucible's own version in uv.lock).

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
