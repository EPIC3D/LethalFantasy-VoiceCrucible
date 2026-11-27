"""Doubled retakes of very short lines."""


import numpy as np

from voicecrucible.core.jobs import Line
from voicecrucible.worker import primer


def _line(text, attempt):
    return Line(key="K", character="A", text=text, voice="v", attempt=attempt)


def test_short_retakes_are_doubled_and_longer_ones_primed():
    assert not primer.wants_double(_line("Squish!", 1))
    assert primer.wants_double(_line("Squish!", 2)) and not primer.wants_primer(_line("Squish!", 2))
    assert primer.wants_double(_line("Stand back!", 3))
    assert not primer.wants_double(_line("Look out below!", 2)) and primer.wants_primer(_line("Look out below!", 2))
    assert primer.doubled(_line("Stomp!", 2)).params["spoken_text"] == "Stomp! Stomp!"


def test_double_cut_between_the_two_times():
    sr = 1000
    times = [{"word": "Stand", "start": 0.1, "end": 0.3}, {"word": "back!", "start": 0.35, "end": 0.6},
             {"word": "Stand", "start": 1.0, "end": 1.2}, {"word": "back!", "start": 1.25, "end": 1.5}]
    assert primer.double_cut(np.zeros(2000), sr, times, 2) == 800
