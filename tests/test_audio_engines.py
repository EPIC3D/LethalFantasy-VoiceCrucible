"""Tests for audio helpers and engine plumbing that need no models."""

import numpy as np
import pytest

from voicecrucible.core import audio
from voicecrucible.engines import base
from voicecrucible.engines.seedvc import SeedVC, SeedVCNotInstalled


def test_trim_tail_cuts_quiet_decay():
    sr = 16000
    loud = 0.5 * np.sin(np.linspace(0, 2000, sr)).astype(np.float32)
    y = np.concatenate([loud, 0.0005 * np.ones(sr, np.float32)])  # 1 s voice + 1 s faint breath
    out = audio.trim_tail(y, sr)
    assert sr < len(out) < 1.3 * sr and abs(out[-1]) < 1e-3


def test_encode_decode_roundtrip():
    y = 0.3 * np.sin(np.linspace(0, 500, 8000)).astype(np.float32)
    back, sr = audio.decode(audio.encode(y, 16000, "wav"))
    assert sr == 16000 and np.allclose(back, y, atol=1e-3)


def test_unknown_engine_and_seed_per_attempt():
    with pytest.raises(ValueError, match="unknown engine"):
        base.create("nope")
    from voicecrucible.core.jobs import Line
    a = Line(key="K", character="A", text="x", attempt=1)
    b = Line(key="K", character="A", text="x", attempt=2)
    assert base.seed_for(a) != base.seed_for(b) and base.seed_for(a) == base.seed_for(Line(key="K", character="B", text="y"))


def test_missing_seedvc_is_reported_clearly(tmp_path):
    with pytest.raises(SeedVCNotInstalled, match="optional component"):
        SeedVC(tmp_path)
