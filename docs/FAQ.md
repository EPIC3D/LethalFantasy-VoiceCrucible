# FAQ – Voice Crucible

Questions about **playing** voices in the game: see the
[LethalFantasy TTS FAQ](https://github.com/EPIC3D/LethalFantasy-TTS/blob/main/docs/FAQ.md).

### Can I use any voice – also a male voice?

Yes. A character speaks with the voice of its **reference clip** (10–25 s of clean speech). Make your own
profile (`crucible.cmd profile new my-voices --from lethalfantasy`), replace that character's clip in its
`voices\chatterbox\` folder and select the profile – see [PROFILES.md](PROFILES.md). Only use voices you have
the right to use.

### Can I add a new character?

No. Voice Crucible only voices the dialogue lines of the game (from your game's export) – it cannot create new
characters or new lines. If a game update adds a new speaking character, it is picked up automatically: it is
added to your profile and rendered once you give it a reference clip.

### Which voices does it use out of the box?

The bundled `lethalfantasy` profile: the same voices and settings as the LethalFantasy TTS demo packs
(Chatterbox, no acting director). It is updated with every Voice Crucible release. Your own profiles are never
changed by updates.

### Do I need an NVIDIA GPU? What about AMD / Intel / Mac?

Rendering needs an NVIDIA RTX 20 or newer (or GTX 16) with 8 GB VRAM. AMD and Intel are not supported yet;
a PC without a supported GPU can still be the coordinator. See [GPU.md](GPU.md).

### How long does a full render take?

About 6,400 lines. On one 8 GB RTX 40-series card with Chatterbox: roughly 3–4 s per line, so about 6–7 hours
(acting packs: about 14 s per line). More PCs as workers divide the time.

### Can I stop and continue later?

Yes. Stop the worker or the coordinator with Ctrl+C; the queue is kept and continues where it stopped. Lines
already in the queue are not queued twice.

### How much disk space?

About 11 GB for the default packs, about 22 GB with acting packs, plus a few hundred MB for the finished
voice pack. `INSTALLED.txt` shows what is installed where.

### Is my game text sent anywhere?

No – everything runs on your PCs. The only exception: if you choose an online AI director
(`crucible direct` with a cloud API), the lines of the scenes you direct go to that service; the command
shows where and asks first.

### Does it make the Memory Orb audiobook?

Not yet – the plugin plays it, but Voice Crucible does not render it.

### Linux?

Not tested yet (planned). Windows 11 is the supported system for now.

### Where do I report a bug?

Open an issue and paste the output of `crucible.cmd diagnose` (personal data is removed). See
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) first.
