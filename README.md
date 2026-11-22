# LethalFantasy Voice Crucible

Text in, magical voices out. Voice Crucible renders voice packs for the
[LethalFantasy TTS](https://github.com/EPIC3D/LethalFantasy-TTS) plugin on your own NVIDIA GPU(s) –
one machine or several on your local network.

> **Beta – tested on Windows 11 with NVIDIA GPUs only.** It works for us; please report what does not.

- Speaks every dialogue line of the game in the characters' voices – from **your own game's** line export.
- Checks every line automatically (all words spoken, start not cut off, same voice, clean audio) and renders
  failed lines again.
- Default packs with Chatterbox; optional **acting packs** (Qwen3-TTS + Seed-VC) with per-line acting directions.
- Several PCs can render together; progress in a small web page (the watcher).
- Not included (yet): the Memory Orb audiobook (`voices\<language>\STORY\`) – the plugin plays it, but Voice
  Crucible does not render it.

## How it works

```mermaid
flowchart TD
    G[Your game + LethalFantasy TTS plugin<br/>line export] --> R[crucible render<br/>coordinator PC]
    P[Your profile<br/>characters, reference voices, acting notes] --> R
    D[Optional: directions.json<br/>crucible direct / AI] -.-> R
    R --> Q[(Job queue)]
    Q <-->|encrypted, paired| W1[Worker PC 1]
    Q <-->|encrypted, paired| W2[Worker PC 2]
    W1 & W2 --> E[Engine: Chatterbox, or Qwen + Seed-VC]
    E --> C{Quality checks<br/>words · voice · audio · pitch}
    C -- failed --> Q
    C -- passed --> O[output\voices\&lt;language&gt;\&lt;CHARACTER&gt;\KEY.ogg]
    O --> M[Copy into the plugin's voices folder]
    Q --> V[Watcher page<br/>progress, workers, problems]
```

![The watcher: two PCs rendering together](docs/images/watcher.png)

*Two PCs rendering together. Every line is checked automatically – wrong words, another voice, bad audio or
a wrong name are caught and rendered again.*

## Quick start

1. Unzip into a folder on an SSD (e.g. `D:\VoiceCrucible`), run **`setup.cmd`** – it shows what it will
   download and asks first.
2. Nothing to prepare for the voices: the bundled **`lethalfantasy` profile** has the demo voices of the
   LethalFantasy TTS plugin. Want your own? [docs/PROFILES.md](docs/PROFILES.md).
3. Export the game's lines with the plugin (`[Developer] ExportLines = true`, play until the first dialogue
   line appears).
4. Run `coordinator.cmd` and `watcher.cmd`. In the watcher: **Pair and start worker on this PC**, choose the
   export folder (`<game>\BepInEx\LFTTS-export`) and **Start rendering**. (old path was (`<game>\BepInEx\LethalFantasyTTS`)
5. The pack is in `output\voices\`; **Report** lists lines with problems.

Everything also works on the command line: `crucible.cmd render --lines ...` (see docs/INSTALL.md).

Step by step: [docs/INSTALL.md](docs/INSTALL.md) · more PCs: [docs/WORKERS.md](docs/WORKERS.md) ·
settings: [docs/CONFIG.md](docs/CONFIG.md) · profiles: [docs/PROFILES.md](docs/PROFILES.md) · problems: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) · **FAQ: [docs/FAQ.md](docs/FAQ.md)**

## System requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Windows 11 (others untested) | Windows 11 |
| GPU (worker) | NVIDIA RTX 20 / GTX 16, 8 GB VRAM, driver 570+ | RTX 40/50, 12–16 GB VRAM |
| Disk | ~11 GB (default packs), ~22 GB with acting | SSD / NVMe |
| RAM | 16 GB | 16 GB or more |

A PC without a supported GPU can still run the coordinator. AMD and Intel GPUs are not supported (yet).
Details and measured speeds: [docs/GPU.md](docs/GPU.md).

**Ad blockers, network filters, firewalls, antivirus:** programs that filter network traffic on your PC (e.g.
AdGuard, some antivirus "web protection") can cut off connections to the watcher (`http://127.0.0.1:5132`) or
between workers and the coordinator (ports 5130/5131 on the local network) – the watcher then shows
"not reachable" or workers go offline at random. Allow `127.0.0.1`, the Voice Crucible folder's `python.exe`
and the local network ports in that program, or pause it to test. Windows Firewall asks once on the
coordinator PC – allow it for private networks.

## What you see running

Voice Crucible runs only while its windows are open – no service, no background process after you close them.

| You started | Task Manager (0.1.0b5) | From 0.1.0b6 |
|---|---|---|
| `coordinator.cmd` | a console window with `python.exe` (from `runtime\venv\Scripts\`) | window title **Voice Crucible - coordinator** |
| `worker.cmd` | a console window with `python.exe` (from `runtime\venv\Scripts\`) | window title **Voice Crucible - worker** |
| `setup.cmd` | a console window with `uv.exe` / `python.exe` | window title **Voice Crucible - setup** |

The process itself is always the private `python.exe` inside the Voice Crucible folder (Task Manager →
Details → right-click → *Open file location* shows `...\VoiceCrucible\runtime\venv\Scripts\`). Optional
Seed-VC runs as a second `python.exe` from `runtime\components\seed-vc\.venv\` while a worker uses it.

## Safety and transparency

- Nothing is installed outside the Voice Crucible folder: no admin rights, no PATH changes, no background
  service, no autostart. Uninstall = delete the folder. `INSTALLED.txt` lists every installed file set and where it is.
- Every download – what it does, source, license, size – is shown before it starts:
  [docs/DOWNLOADS.md](docs/DOWNLOADS.md).
- Workers open no port; they connect out to your paired coordinator only (encrypted, pinned certificate,
  local network only).
- Updates happen only when you start them; downloads are signature-checked. Threat model:
  [docs/SECURITY.md](docs/SECURITY.md).
- No personal data is collected or sent. The only thing that can leave your network is game text sent to an
  online AI director – only if you choose one, and the command asks first.

## Reporting bugs

Please open an issue: <https://github.com/EPIC3D/LethalFantasy-VoiceCrucible/issues> and attach the output of

```
crucible.cmd diagnose
```

(saved as `logs\diagnose.txt`). It contains only technical facts – versions, OS, GPU, driver, VRAM, settings
and recent log lines – with IP addresses, computer name, user name and keys removed. Please check it before
posting. We never ask for personal data or a full dxdiag.

## Game content

LethalFantasy is made by **LadyAlice**. This is an unofficial fan tool, not affiliated with or endorsed by
the game's author. It contains no game text; it reads the lines from your own copy of the game.

## No warranty

Voice Crucible is a free hobby project, provided **as is, without warranty of any kind** and without
liability (see [LICENSE](LICENSE)). It downloads large third-party components and uses your GPU heavily –
use it at your own risk.

## License

Code: MIT (see [LICENSE](LICENSE)) – except one small bridge file to Seed-VC, which is GPL-3.0.
Third-party engines and model weights are downloaded from their own sources under their own licenses –
see [docs/LICENSES.md](docs/LICENSES.md).

## Related

- [LethalFantasy TTS](https://github.com/EPIC3D/LethalFantasy-TTS) – the BepInEx plugin that plays the voice
  packs in the game.

## Support

If you enjoy the game, please support its author, LadyAlice, first:
<https://www.patreon.com/cw/LadyAliceR18>.

If you'd also like to support this tool:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/E6Z42AUOBQ)
