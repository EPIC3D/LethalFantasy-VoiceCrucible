"""Small audio helpers: decode, pad, resample-free encode to OGG Vorbis / WAV (libsndfile via soundfile)."""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf

LEAD_IN_SECONDS = 0.15  # silence before the voice, so the first word is never clipped on playback
OGG_QUALITY = 0.6  # libsndfile Vorbis quality 0..1 (≈ ffmpeg -q:a 6 of the old pipeline)
_OGG_BLOCK = 8192  # frames per write call


def decode(data: bytes) -> tuple[np.ndarray, int]:
    """Audio file bytes -> mono float32 samples and sample rate."""
    y, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    return y.mean(axis=1), sr


def pad_lead_in(y: np.ndarray, sr: int, seconds: float = LEAD_IN_SECONDS) -> np.ndarray:
    """Prepend a short silence."""
    return np.concatenate([np.zeros(int(sr * seconds), np.float32), y.astype(np.float32)])


def quiet_lead_noise(y: np.ndarray, sr: int, silence: float = 0.002, max_blip: float = 0.12,
                     max_share: float = 0.3) -> np.ndarray:
    """Mute a short noise before the speech (heard: a gulp before "Definitely"). Only a sound that is short (at most
    `max_blip` s), quiet (below `max_share` of the peak) and followed by silence is muted – a soft spoken start or a
    breath that runs into the first word is kept. Muted, not cut: the timing stays the same."""
    hop = max(1, int(sr * 0.0125))
    n = len(y) // hop
    if n < 4:
        return y
    rms = np.sqrt((y[: n * hop].astype(np.float64).reshape(n, hop) ** 2).mean(axis=1))
    peak = rms.max()
    if peak <= 0:
        return y
    loud = rms > silence
    runs, i = [], 0  # (start, end) frames of each stretch of sound
    while i < n:
        if loud[i]:
            j = i
            while j < n and loud[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    mute_to = 0
    for (a, b), nxt in zip(runs, runs[1:], strict=False):  # each sound with the one after it
        short, quiet = (b - a) * hop / sr <= max_blip, rms[a:b].max() < max_share * peak
        if not (short and quiet and nxt[0] > b):  # the first real sound: stop
            break
        mute_to = b
    if not mute_to:
        return y
    out = y.astype(np.float32).copy()
    out[: mute_to * hop] = 0.0
    return out


def envelope(y: np.ndarray, sr: int, seconds: float = 2.0, step: float = 0.01) -> list[float]:
    """Level of the first `seconds` in `step` slices, 0..1 of the whole take's peak (for the watcher's trim view)."""
    hop = max(1, int(sr * step))
    peak = float(np.abs(y).max()) or 1.0
    part = y[: int(sr * seconds)]
    return [round(float(np.sqrt(np.mean(part[i:i + hop] ** 2))) / peak, 4) for i in range(0, len(part), hop)]


def speech_start(y: np.ndarray, sr: int, share: float = 0.25, silence: float = 0.002, margin: float = 0.03) -> float:
    """Where the speech itself starts (seconds): the level first reaches `share` of the peak; going back while sound
    continues keeps a soft start; a little `margin` is left before it. A suggestion for a manual trim."""
    hop = max(1, int(sr * 0.01))
    n = len(y) // hop
    if n < 2:
        return 0.0
    rms = np.sqrt((y[: n * hop].astype(np.float64).reshape(n, hop) ** 2).mean(axis=1))
    if rms.max() <= 0:
        return 0.0
    i = int(np.argmax(rms >= share * rms.max()))
    while i > 0 and rms[i - 1] > silence:
        i -= 1
    return max(0.0, i * hop / sr - margin)


def insert_pause(y: np.ndarray, sr: int, at: float, seconds: float) -> np.ndarray:
    """Insert `seconds` of silence at `at` seconds – a dramatic pause between sentences, or a longer start (at 0)."""
    i = int(max(0.0, min(at, len(y) / sr)) * sr)
    return np.concatenate([y[:i], np.zeros(int(seconds * sr), np.float32), y[i:]]).astype(np.float32)


def trim_start(y: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    """Cut the first `seconds` (a bad sound before a good line), fade in over 10 ms, put the usual lead-in back."""
    out = y[int(max(0.0, seconds) * sr):].astype(np.float32).copy()
    fade = min(int(0.01 * sr), len(out))
    out[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    return pad_lead_in(out, sr)


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
        # written in blocks: libsndfile crashes the whole process when a long Vorbis file is written in one call
        data = np.clip(y, -1, 1).astype(np.float32)
        with sf.SoundFile(buf, "w", sr, 1, format="OGG", subtype="VORBIS", compression_level=1 - OGG_QUALITY) as f:
            for i in range(0, len(data), _OGG_BLOCK):
                f.write(data[i:i + _OGG_BLOCK])
    elif fmt == "wav":
        sf.write(buf, np.clip(y, -1, 1), sr, format="WAV", subtype="PCM_16")
    else:
        raise ValueError(f"unknown audio format {fmt!r}")
    return buf.getvalue()
