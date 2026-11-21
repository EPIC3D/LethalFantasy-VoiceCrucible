"""Small audio helpers: decode, pad, resample-free encode to OGG Vorbis / WAV (libsndfile via soundfile)."""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf

LEAD_IN_SECONDS = 0.15  # silence before the voice, so the first word is never clipped on playback
OGG_QUALITY = 0.6  # libsndfile Vorbis quality 0..1 (≈ ffmpeg -q:a 6 of the old pipeline)


def decode(data: bytes) -> tuple[np.ndarray, int]:
    """Audio file bytes -> mono float32 samples and sample rate."""
    y, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    return y.mean(axis=1), sr


def pad_lead_in(y: np.ndarray, sr: int, seconds: float = LEAD_IN_SECONDS) -> np.ndarray:
    """Prepend a short silence."""
    return np.concatenate([np.zeros(int(sr * seconds), np.float32), y.astype(np.float32)])


def trim_tail(y: np.ndarray, sr: int, threshold_db: float = -40.0, keep: float = 0.12) -> np.ndarray:
    """Cut a trailing breath/whisper decay: end shortly after the level was last within `threshold_db` of the peak."""
    hop, frame = 256, 1024
    if len(y) < frame:
        return y
    frames = np.lib.stride_tricks.sliding_window_view(y, frame)[::hop]
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    db = 20 * np.log10(rms / (rms.max() + 1e-9) + 1e-9)
    loud = np.where(db > threshold_db)[0]
    end = min(len(y), (loud[-1] + 1) * hop + frame + int(keep * sr)) if len(loud) else len(y)
    out = y[:end].astype(np.float32).copy()
    fade = min(int(0.03 * sr), len(out))
    out[len(out) - fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return out


def encode(y: np.ndarray, sr: int, fmt: str = "ogg") -> bytes:
    """Encode mono samples as 'ogg' (Vorbis) or 'wav' (16-bit PCM)."""
    buf = io.BytesIO()
    if fmt == "ogg":
        sf.write(buf, np.clip(y, -1, 1), sr, format="OGG", subtype="VORBIS",
                 compression_level=1 - OGG_QUALITY)
    elif fmt == "wav":
        sf.write(buf, np.clip(y, -1, 1), sr, format="WAV", subtype="PCM_16")
    else:
        raise ValueError(f"unknown audio format {fmt!r}")
    return buf.getvalue()
