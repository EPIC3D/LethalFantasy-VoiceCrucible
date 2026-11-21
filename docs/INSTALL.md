# Install and first render

Tested on **Windows 11 with NVIDIA GPUs** (RTX 40 and RTX 50 series cards). See [GPU.md](GPU.md) for requirements.

## 1. Install (every machine)

1. Unzip the release into a folder **on an SSD/NVMe**, e.g. `D:\VoiceCrucible`. No admin rights needed.
2. Double-click **`setup.cmd`**. It shows:
   - your GPU and whether it is supported,
   - what will be downloaded – each part with source, license and size ([DOWNLOADS.md](DOWNLOADS.md) explains them),
   - the drive type and free space,
   and asks before downloading anything. Answer **no** to the acting engine (Qwen) and Seed-VC unless you
   want acting packs – you can add them later by running `setup.cmd` again.
3. When it is done, `INSTALLED.txt` lists everything that was installed and where. The setup log is in `logs\`.

Uninstall = delete the folder.

## 2. Get the reference voices and the game's lines

- **Profile** (your characters and their reference voices): `crucible.cmd profile new lethalfantasy`, then
  follow [PROFILES.md](PROFILES.md) – the game's speakers are added automatically, you add one reference clip
  per character. Without a profile `render` stops with a clear message.
- **Lines**: in the LethalFantasy TTS plugin set `[Developer] ExportLines = true` in `BepInEx\config\lf-tts.cfg`,
  start the game once, then set it back to `false`. The export is in `<game>\BepInEx\LethalFantasyTTS\`.

## 3. Render (one machine)

Open a command prompt in the Voice Crucible folder:

1. `coordinator.cmd` – keep this window open (job queue + watcher).
2. Pair this machine as its own worker, once: `pair.cmd`, enter the code shown by the coordinator.
3. `worker.cmd` – keep it open.
4. Queue the lines: `crucible.cmd render --lines "<game>\BepInEx\LethalFantasyTTS"`
   - try first with `--dry-run` (shows what would be queued) or `--limit 20`.
5. Watch the progress: `watcher.cmd` (opens http://127.0.0.1:5132).
6. When done: `crucible.cmd report`. The voice pack is in `output\voices\en\AKIPO|RED|BLUE\`, lines with
   problems are listed in `output\report.tsv`.

Copy `output\voices\` into the game's `BepInEx\plugins\LethalFantasyTTS\` to use the pack.

More machines: [WORKERS.md](WORKERS.md). Settings: [CONFIG.md](CONFIG.md). Problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Acting packs (optional)

Needs the Qwen and Seed-VC components (`setup.cmd` again). Then render with `--engine qwen_vc`. Acting
directions make a big difference: use a ready `directions.json` (`[director] mode = "file"`) or create one
with an AI (`[director] mode = "api"`, then `crucible.cmd direct --lines ...` – it shows where the text goes
and asks first).

## Updating

`crucible.cmd update` checks GitHub, shows the changes and asks. The download is verified (signature) before
anything changes; settings, pairings, voices and output stay. `crucible.cmd update --rollback` goes back.
With several machines: update the **workers first** (watcher → *Update workers*), the coordinator last.
