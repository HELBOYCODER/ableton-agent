# -*- coding: utf-8 -*-
"""Music theory & generative groove engine for ableton-agent."""

import random

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


def parse_pitch(note_str, default_octave=3):
    """Convert note string like 'C4', 'F#3', 'Bb2' or int to MIDI pitch (0-127)."""
    if isinstance(note_str, int):
        return max(0, min(127, note_str))
    note_str = str(note_str).strip()
    if note_str.isdigit():
        return max(0, min(127, int(note_str)))
    import re
    m = re.match(r"^([A-Ga-g][#b]?)(-?\d+)?$", note_str)
    if not m:
        return 60  # fallback to middle C
    name, oct_s = m.group(1).capitalize(), m.group(2)
    semitone = NOTE_TO_INT.get(name, 0)
    octave = int(oct_s) if oct_s is not None else default_octave
    # MIDI note 60 is C4 (with C-1 = 0, C4 = (4 + 1) * 12 = 60)
    pitch = (octave + 1) * 12 + semitone
    return max(0, min(127, pitch))


def get_chord_notes(root_note, chord_type="min7", octave=3):
    """Return list of MIDI pitches for a chord."""
    base = parse_pitch(root_note, default_octave=octave)
    intervals = CHORD_INTERVALS.get(chord_type.lower(), CHORD_INTERVALS["min"])
    return [base + iv for iv in intervals if base + iv <= 127]


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


def humanize_notes(notes, velocity_variance=8, timing_jitter=0.015, swing=0.0):
    """
    Humanize MIDI notes to remove robotic AI feel:
    - velocity_variance: random velocity fluctuation (+/- range)
    - timing_jitter: micro-timing offset in beats
    - swing: delayed offbeat eighth/sixteenth notes (0.0 = straight, 0.2 = swing)
    """
    humanized = []
    for n in notes:
        n_copy = dict(n)
        start = float(n_copy.get("start", 0.0))
        length = float(n_copy.get("length", 0.25))
        vel = int(n_copy.get("velocity", 100))

        # Apply swing on offbeats (every odd 16th note, step 0.25)
        step_pos = round(start / 0.25)
        if step_pos % 2 == 1 and swing > 0:
            start += swing * 0.1

        # Apply micro-jitter
        if timing_jitter > 0:
            jitter = (random.random() - 0.5) * 2 * timing_jitter
            start = max(0.0, start + jitter)

        # Apply velocity variation
        if velocity_variance > 0:
            v_delta = random.randint(-velocity_variance, velocity_variance)
            vel = max(1, min(127, vel + v_delta))

        n_copy["start"] = round(start, 4)
        n_copy["length"] = round(length, 4)
        n_copy["velocity"] = vel
        humanized.append(n_copy)
    return humanized
