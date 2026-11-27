# System requirements and GPU support

**Tested:** Windows 11 with NVIDIA RTX 40 (8 GB) and RTX 50 (16 GB) series cards. Everything else below
is expected to work but has not been tested – reports welcome.

## Requirements

| | Coordinator only | Worker – default voice packs (Chatterbox) | Worker – acting packs (Qwen + Seed-VC) |
|---|---|---|---|
| OS | Windows 11 (Windows 10 / Linux untested) | same | same |
| GPU | none | NVIDIA RTX 20 or newer / GTX 16, **8 GB VRAM** (6 GB: untested, small batches) | NVIDIA, 8 GB VRAM works, **12–16 GB recommended** |
| NVIDIA driver | – | 570 or newer | 570 or newer |
| Disk | ~0.5 GB | ~11 GB | ~22 GB |
| Drive | any | SSD / NVMe recommended (models load at every start) | SSD / NVMe recommended |
| RAM | 4 GB | 16 GB recommended | 16 GB recommended |

Measured speed on an 8 GB RTX 40-series card, including all quality checks:
- Chatterbox: about **3–4 s per line** (model loading ~45–60 s once per start),
- Qwen + Seed-VC: about **14 s per line**.

## How long a whole voice pack takes

LethalFantasy beta 1.0.3: about **6,300 voiced lines** (~6,500 files with the he/she/they variants). Numbers
measured on Windows 11 (8 GB RTX 40-series and 16 GB RTX 50-series cards); first measurements, a full run
updates them.

| Step | 8 GB card | 16 GB card | Whole game |
|---|---|---|---|
| Directing, local LLM `qwen3:14b` (Ollama) | does not fit | ~20 lines/min (measured, whole game) | **~5.3 h** on one 16 GB card (measured) |
| Directing, local LLM `qwen3:8b` | ~25 lines/min, weaker directions | – | ~4–5 h (quick tests only) |
| Chatterbox render + checks | ~3–4 s per line | faster (bigger batches) | ~6–7 h on one 8 GB card |
| Breeze TTS 2 render + checks | does not fit (needs 12 GB+) | ~25–30 s per line incl. checks and retakes | ~45–50 h on one 16 GB card |
| Qwen + Seed-VC render + checks | ~14 s per line | – | ~25 h on one 8 GB card |

Plan big runs so the machines overlap:
- `crucible direct --render`: while the language model directs on one PC, the other PCs already render the
  directed scenes. The worker on the directing PC waits and joins in when directing is done (the model is
  unloaded automatically).
- Directions are made **once** and stored in `work\directions.json`; every engine and every later render reuses
  them. A game update only directs the new lines.
- Example: directing on a 16 GB card while an 8 GB card renders Chatterbox, then both render → a complete
  default pack in **about one night (~8–10 h)**.
- Very long scenes (100+ random alternatives, e.g. growth reactions) are sent in parts with only the nearby
  lines as context – a whole 170-line list does not fit a local model's context and gave empty directions.
- Keep the language model fully on the GPU (`ollama ps` shows "100% GPU"); if part of it spills into system RAM
  it gets many times slower. `[director] context_length` (default 4096) sets how much VRAM it needs.

## GPU support

- **NVIDIA (supported):** one PyTorch build (CUDA 12.8) for RTX 20, 30, 40, 50 and GTX 16. RTX 20 and GTX 16
  have no bf16 and run Qwen in fp16 (slower; untested). GTX 10 and older: not supported.
- `setup.cmd` decides by capability – compute capability, driver version, VRAM – not by card name, and says
  what to do (e.g. "driver too old – install 570 or newer").
- **AMD Radeon:** experimental only (PyTorch ROCm; Linux is further along than Windows). Not installed by setup.
- **Intel Arc:** experimental only (PyTorch XPU). Not installed by setup.
- **No supported GPU:** the machine can still be the coordinator; another machine renders as a worker.
