# -*- coding: utf-8 -*-
"""Music theory & generative groove engine for ableton-agent."""

import os
import random
import re

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_TO_INT = {name: i for i, name in enumerate(NOTE_NAMES)}
# Flat aliases
NOTE_TO_INT.update({"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10})

SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "pentatonic_minor": [0, 3, 5, 7, 10],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "blues": [0, 3, 5, 6, 7, 10],
}

CHORD_ALIASES = {
    "major": "maj", "M": "maj", "": "maj",
    "minor": "min", "m": "min", "-": "min",
    "m7": "min7", "minor7": "min7", "min-7": "min7",
    "m9": "min9", "minor9": "min9",
    "major7": "maj7", "M7": "maj7",
    "major9": "maj9",
    "dom7": "7", "dominant7": "7",
    "diminished": "dim", "augmented": "aug",
    "sus": "sus4",
}

CHORD_INTERVALS = {
    "maj": [0, 4, 7],
    "min": [0, 3, 7],
    "dim": [0, 3, 6],
    "aug": [0, 4, 8],
    "sus4": [0, 5, 7],
    "sus2": [0, 2, 7],
    "7": [0, 4, 7, 10],
    "maj7": [0, 4, 7, 11],
    "min7": [0, 3, 7, 10],
    "min9": [0, 3, 7, 10, 14],
    "maj9": [0, 4, 7, 11, 14],
}

PROGRESSIONS = {
    "lofi": ["min9", "min7", "maj7", "min7"],
    "house": ["min7", "min7", "maj7", "sus4"],
    "techno": ["min", "min", "dim", "min"],
    "pop": ["maj", "maj", "min", "maj"],
}


# Ableton Live labels MIDI note 60 as C3, so an octave number maps to
# (octave + 2) * 12. Set ABLETON_AGENT_MIDDLE_C=C4 for scientific pitch
# notation (the convention used by most DAWs other than Live).
MIDDLE_C_OCTAVE = 4 if (os.environ.get("ABLETON_AGENT_MIDDLE_C", "C3").upper() == "C4") else 3
OCTAVE_OFFSET = 5 - MIDDLE_C_OCTAVE


def parse_pitch(note_str, default_octave=3):
    """Convert a note name ('C3', 'F#3', 'Bb2') or int to a MIDI pitch (0-127).

    Octave numbers follow Live's display convention: C3 == 60.
    """
    if isinstance(note_str, int):
        return max(0, min(127, note_str))
    note_str = str(note_str).strip()
    if note_str.lstrip("-").isdigit():
        return max(0, min(127, int(note_str)))
    m = re.match(r"^([A-Ga-g][#b]?)(-?\d+)?$", note_str)
    if not m:
        return 60  # fallback to middle C
    name, oct_s = m.group(1)[0].upper() + m.group(1)[1:], m.group(2)
    semitone = NOTE_TO_INT.get(name, 0)
    octave = int(oct_s) if oct_s is not None else default_octave
    pitch = (octave + OCTAVE_OFFSET) * 12 + semitone
    return max(0, min(127, pitch))


def get_chord_notes(root_note, chord_type="min7", octave=3):
    """Return list of MIDI pitches for a chord."""
    base = parse_pitch(root_note, default_octave=octave)
    key = str(chord_type or "").strip()
    key = CHORD_ALIASES.get(key, CHORD_ALIASES.get(key.lower(), key.lower()))
    intervals = CHORD_INTERVALS.get(key, CHORD_INTERVALS["min"])
    return [base + iv for iv in intervals if 0 <= base + iv <= 127]


def euclidean_rhythm(hits, steps):
    """
    Bjorklund Euclidean algorithm.
    Generates maximally even rhythms (e.g. hits=3, steps=8 -> Tresillo rhythm [1,0,0,1,0,0,1,0]).
    """
    if hits <= 0:
        return [0] * steps
    if hits >= steps:
        return [1] * steps

    pattern = [[1]] * hits + [[0]] * (steps - hits)
    while len(pattern) > 1:
        ones = [x for x in pattern if x[0] == 1]
        zeros = [x for x in pattern if x[0] == 0]
        if not zeros or not ones:
            break
        min_len = min(len(ones), len(zeros))
        new_pattern = []
        for i in range(min_len):
            new_pattern.append(ones[i] + zeros[i])
        new_pattern.extend(ones[min_len:])
        new_pattern.extend(zeros[min_len:])
        pattern = new_pattern

    res = []
    for sub in pattern:
        res.extend(sub)
    return res


def humanize_notes(notes, velocity_variance=8, timing_jitter=0.015, swing=0.0, rng=None):
    """
    Humanize MIDI notes to remove robotic AI feel:
    - velocity_variance: random velocity fluctuation (+/- range)
    - timing_jitter: micro-timing offset in beats
    - swing: 0.0 = straight, 1.0 = offbeat 16ths pushed a full half-step late
    - rng: optional random.Random for reproducible output
    """
    rng = rng or random
    humanized = []
    for n in notes:
        n_copy = dict(n)
        start = float(n_copy.get("start", 0.0))
        length = float(n_copy.get("length", 0.25))
        vel = int(n_copy.get("velocity", 100))

        # Apply swing on offbeats (every odd 16th note, step 0.25)
        step_pos = int(round(start / 0.25))
        if step_pos % 2 == 1 and swing > 0:
            start += swing * 0.125

        # Apply micro-jitter
        if timing_jitter > 0:
            jitter = (rng.random() - 0.5) * 2 * timing_jitter
            start = max(0.0, start + jitter)

        # Apply velocity variation
        if velocity_variance > 0:
            v_delta = rng.randint(-velocity_variance, velocity_variance)
            vel = max(1, min(127, vel + v_delta))

        n_copy["start"] = round(start, 4)
        n_copy["length"] = round(length, 4)
        n_copy["velocity"] = vel
        humanized.append(n_copy)
    return humanized
