# -*- coding: utf-8 -*-
import random

import pytest

from ableton_agent import theory


@pytest.mark.parametrize("name,pitch", [
    ("C3", 60),      # Live displays MIDI 60 as C3
    ("c3", 60),
    ("C4", 72),
    ("A2", 57),
    ("F#3", 66),
    ("Bb2", 58),
    (60, 60),
    ("60", 60),
])
def test_parse_pitch(name, pitch):
    assert theory.parse_pitch(name) == pitch


def test_parse_pitch_clamps_and_falls_back():
    assert theory.parse_pitch("C99") == 127
    assert theory.parse_pitch("not a note") == 60


@pytest.mark.parametrize("chord_type", ["min7", "m7", "minor7"])
def test_chord_aliases(chord_type):
    assert theory.get_chord_notes("C3", chord_type) == [60, 63, 67, 70]


def test_euclidean_tresillo():
    assert sum(theory.euclidean_rhythm(3, 8)) == 3
    assert len(theory.euclidean_rhythm(3, 8)) == 8


@pytest.mark.parametrize("hits,steps", [(0, 8), (8, 8), (9, 8), (5, 16), (-1, 4)])
def test_euclidean_always_returns_steps_values(hits, steps):
    pattern = theory.euclidean_rhythm(hits, steps)
    assert len(pattern) == steps
    assert set(pattern) <= {0, 1}


def test_humanize_is_deterministic_with_a_seeded_rng():
    notes = [{"pitch": 36, "start": 0.0, "length": 0.25, "velocity": 100}]
    a = theory.humanize_notes(notes, rng=random.Random(7))
    b = theory.humanize_notes(notes, rng=random.Random(7))
    assert a == b


def test_humanize_keeps_notes_in_range():
    notes = [{"pitch": 36, "start": 0.0, "length": 0.25, "velocity": 127} for _ in range(50)]
    for note in theory.humanize_notes(notes, swing=0.5):
        assert 1 <= note["velocity"] <= 127
        assert note["start"] >= 0.0
