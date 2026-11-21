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

## GPU support

- **NVIDIA (supported):** one PyTorch build (CUDA 12.8) for RTX 20, 30, 40, 50 and GTX 16. RTX 20 and GTX 16
  have no bf16 and run Qwen in fp16 (slower; untested). GTX 10 and older: not supported.
- `setup.cmd` decides by capability – compute capability, driver version, VRAM – not by card name, and says
  what to do (e.g. "driver too old – install 570 or newer").
- **AMD Radeon:** experimental only (PyTorch ROCm; Linux is further along than Windows). Not installed by setup.
- **Intel Arc:** experimental only (PyTorch XPU). Not installed by setup.
- **No supported GPU:** the machine can still be the coordinator; another machine renders as a worker.
