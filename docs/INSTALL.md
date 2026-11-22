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

## 2. Voices and the game's lines

- **Voices**: the bundled `lethalfantasy` profile (the plugin's demo voices) is used by default – nothing to do.
  For your own voices see [PROFILES.md](PROFILES.md).
- **Lines**: in the LethalFantasy TTS plugin set `[Developer] ExportLines = true` in `BepInEx\config\lf-tts.cfg`,
  start a game and play until the first dialogue line appears (the export is written then, not at the main
  menu), then set it back to `false`. The export is in `<game>\BepInEx\LFTTS-export\` (plugin 0.5.1+;
  0.5.0 wrote it to `<game>\BepInEx\LethalFantasyTTS\`).

## 3. Render (one machine)

**In the watcher (easiest):**

1. `coordinator.cmd` – keep this window open, then `watcher.cmd` (opens http://127.0.0.1:5132).
2. Workers panel: **Pair and start worker on this PC** (pairs once, then opens the worker in its own window).
3. Render panel: *Browse…* to `<game>\BepInEx\LFTTS-export`, **Check (dry run)** (shows what would be
   rendered), then **Start rendering**.
4. When done: **Report**. The voice pack is in `output\voices\en\AKIPO|RED|BLUE\`, lines with problems are
   listed in `output\report.tsv`.

**Or on the command line** (the buttons run exactly these commands), in the Voice Crucible folder:

1. `coordinator.cmd` – keep this window open (job queue + watcher).
2. Pair this machine as its own worker, once: `pair.cmd`, enter the code shown by the coordinator.
3. `worker.cmd` – keep it open.
4. Queue the lines: `crucible.cmd render --lines "<game>\BepInEx\LFTTS-export"`
   - try first with `--dry-run` (shows what would be queued) or `--limit 20`.
5. Watch the progress: `watcher.cmd` (opens http://127.0.0.1:5132).
6. When done: `crucible.cmd report`. The voice pack is in `output\voices\en\AKIPO|RED|BLUE\`, lines with
   problems are listed in `output\report.tsv`.

Copy `output\voices\` into the game's `BepInEx\plugins\LethalFantasyTTS\` to use the pack. A line that failed
every check still gets its best take (marked "failed – best take used" in the report).

**Check voices again** (no rendering): Render panel → "Re-check voice files" → **Re-check voices**, or
`crucible.cmd recheck`. With "Check files from" (`--from <folder> --lines <export>`) it checks any voice pack, e.g.
the one in the game – that folder is only read; its files are copied into your voice pack folder (a different file
there is kept as `.bak.ogg`) and checked there.
Lines that fail are listed under Problems: listen, then Accept, Redo or Skip.

**After a game update:** export the lines again and run the same `render` command – only the new lines are
rendered, the ones you already have are skipped (`--all` renders everything again).

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
