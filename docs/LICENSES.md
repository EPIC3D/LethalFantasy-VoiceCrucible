# Licenses


- **Voice Crucible code: MIT** ([LICENSE](../LICENSE)) – except the file below.
- **`voicecrucible/vc_bridge/seedvc_bridge.py`: GPL-3.0-or-later.** It imports Seed-VC (GPL-3.0) and runs
  only as a separate process inside the separately installed Seed-VC folder. The MIT code never imports
  it; it talks to it through stdin/stdout. Seed-VC itself is an optional component, downloaded from
  <https://github.com/Plachtaa/seed-vc> at a pinned commit, never bundled.
- Engines and checks are downloaded from their own sources (code + model weights), never bundled:

| Component | Code | Weights |
|---|---|---|
| Chatterbox (Resemble AI) | MIT | MIT (output carries the Perth watermark) |
| Qwen3-TTS (Alibaba Qwen) | Apache-2.0 | Apache-2.0 |
| Seed-VC (optional) | GPL-3.0 | GPL-3.0 |
| Breeze TTS 2 (optional, BreezeBlue) | Apache-2.0 | **BreezeBlue Research and Non-Commercial License** – also covers the audio it generates |
| Whisper (OpenAI) | MIT | MIT |
| resemblyzer | Apache-2.0 | Apache-2.0 |
| UTMOS / SpeechMOS | MIT | MIT (+ Apache-2.0 parts) |
| PyTorch | BSD-3-Clause | – |
| uv (bundled in the release, unchanged; license texts in `third_party/uv/`) | MIT / Apache-2.0 | – |

- **Bundled default profile (`profiles/lethalfantasy/`):** the reference voices are synthetic – short clips
  rendered with [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) voice blends, no
  recording of a real person. The character and place names belong to the game's author, LadyAlice; they
  are used only to match the game's lines.
- Rendered voice files are not covered by these licenses; voice packs made from the game's lines have
  their own terms (see the LethalFantasy TTS repository).

**Breeze TTS 2:** its model weights *and the voices it generates* may only be used for personal, research and other
non-commercial purposes – never sold. Voice packs rendered with Breeze inherit that limit; share them for free only.
Breeze is an optional component and is downloaded from its own sources only when you choose it in `setup.cmd`.
