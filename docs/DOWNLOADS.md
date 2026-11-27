# What Voice Crucible downloads – and why

`setup.cmd` never downloads anything before showing you this list (for the parts you chose) and asking.
Everything is stored **inside the Voice Crucible folder** (`runtime\...`); nothing is installed into Windows,
nothing is added to PATH, nothing runs in the background. The exact files, versions, sizes and folders of
your installation are listed in `INSTALLED.txt`. Uninstall = delete the folder.

The machine-readable version of this page is [`downloads.toml`](../downloads.toml) – the setup reads it.

## Always

| What | What it does | Source | License | Size |
|---|---|---|---|---|
| **uv** (`uv.exe`, included in the zip) | Installs Python and the packages below into this folder, exactly in the versions listed in `uv.lock`. | [astral-sh/uv](https://github.com/astral-sh/uv) | MIT / Apache-2.0 | ~40 MB |
| **Python 3.12** | Runs Voice Crucible. A private copy, not the system Python. | python-build-standalone (via uv) | PSF | ~120 MB |
| **Core packages**: cryptography, numpy, soundfile | Encrypted connection between coordinator and workers (TLS, pairing); audio data; reading/writing audio files. | pypi.org | Apache-2.0/BSD, BSD, BSD | ~70 MB |

This is enough for the **coordinator** and the **watcher** (and a machine without a supported GPU).

## For rendering on an NVIDIA GPU

| What | What it does | Source | License | Download / on disk |
|---|---|---|---|---|
| **PyTorch 2.11 (CUDA 12.8)** | The engine that runs the AI models on the graphics card. One build for RTX 20–50 and GTX 16. Contains NVIDIA's CUDA runtime libraries. | download.pytorch.org | BSD-3-Clause; CUDA libraries: NVIDIA license (redistributable) | ~3 GB / ~4.4 GB |
| **Quality checks**: Whisper (small), resemblyzer, UTMOS, librosa | After every rendered line: Whisper listens and checks that all words were spoken and the start is not cut off; resemblyzer checks that it is still the character's voice; UTMOS rates the audio quality; librosa measures the pitch. Failed takes are rendered again. | pypi.org; Whisper model from OpenAI's server; UTMOS code from [tarepan/SpeechMOS](https://github.com/tarepan/SpeechMOS) v1.2.0 | MIT, Apache-2.0, MIT, ISC | ~1.1 GB / ~1.3 GB |
| **Chatterbox** (engine + model) | Speaks the lines in the character's voice, copied from a short reference clip; emotion strength per line. Used for the default voice packs. Its audio carries Resemble AI's inaudible watermark (marks it as AI-generated). | pypi.org (chatterbox-tts 0.1.7); model: [ResembleAI/chatterbox](https://huggingface.co/ResembleAI/chatterbox) | MIT | ~3.5 GB / ~5 GB |

## Optional: acting packs

| What | What it does | Source | License | Download / on disk |
|---|---|---|---|---|
| **Qwen3-TTS 1.7B VoiceDesign** | Acts each line from a written direction (scene, intent, delivery) – much more expressive than Chatterbox, but its voice changes from line to line, so it is combined with Seed-VC. | pypi.org (qwen-tts 0.1.1); model: [Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign) (+ the *Base* model, 4.3 GB, only if you use clone mode) | Apache-2.0 | ~4.4 GB / ~4.6 GB |
| **Seed-VC** | Voice conversion: turns Qwen's acted line into the character's fixed reference voice, so every line sounds like the same person. Installed into its own folder with its own Python packages and run as a separate program (it is GPL-licensed; Voice Crucible's own code is MIT). Downloaded at a fixed version and checked with a SHA-256 checksum. | [Plachtaa/seed-vc](https://github.com/Plachtaa/seed-vc) (pinned commit); models from Hugging Face (Plachta/Seed-VC and the models it uses) | GPL-3.0 | ~4 GB / ~6 GB |
| **Breeze TTS 2** (optional) | Clean voice cloned from a reference clip that reads a fixed text, acted from the director's written instruction – the best acting of the engines. Needs a 12 GB+ NVIDIA card. Own folder and Python packages, its own local server while a worker uses it. | [breezeblue-ai/breeze-tts](https://github.com/breezeblue-ai/breeze-tts) (pinned commit, SHA-256 checked); model [BreezeBlue/Breeze-TTS-2](https://huggingface.co/BreezeBlue/Breeze-TTS-2) (pinned revision, 7.7 GB on first use) | Code Apache-2.0; weights and generated audio non-commercial | ~3 GB / ~8 GB |

## When the downloads happen

- **During setup:** uv, Python, the packages, Seed-VC's code and packages.
- **On first use:** the AI models (Chatterbox, Qwen, Whisper, UTMOS, Seed-VC's models) are downloaded the
  first time a worker needs them – the worker window shows the progress. They go to `runtime\models\`.

## Saving space

- `runtime\uv-cache\` holds the downloaded package files. It can be deleted after setup (setup downloads
  them again if you change components).
- To remove an optional part, run `setup.cmd` again and answer **no**.

## What is never downloaded or sent

- No game files and no game text: the lines come from your own game (the plugin's export).
- Nothing is sent anywhere, except: if you choose an **online AI director** (`crucible direct` with a cloud
  API), the game lines of the scenes you direct are sent to that service – the command shows where and asks
  first. With a local AI (Ollama, LM Studio) nothing leaves your network.
