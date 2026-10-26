# -*- coding: utf-8 -*-
"""MIDI note read / write / transform. Pure math on note dicts."""

from __future__ import absolute_import, print_function, unicode_literals

import random

from . import hb_util as U


def _get(ctx, track=0, slot=0, pitch_low=0, pitch_high=127,
         time_low=0.0, time_high=None, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if not clip.is_midi_clip:
        raise ValueError("clip is not a midi clip")
    notes = U.read_notes(clip, pitch_low, pitch_high, time_low, time_high)
    return {"notes": notes, "count": len(notes), "length": clip.length}


def _stats(ctx, track=0, slot=0, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if not clip.is_midi_clip:
        raise ValueError("clip is not a midi clip")
    notes = U.read_notes(clip)
    if not notes:
        return {"count": 0, "length": clip.length}
    pitches = [n["pitch"] for n in notes]
    velocities = [n["vel"] for n in notes]
    durations = [n["dur"] for n in notes]
    return {
        "count": len(notes),
        "length": clip.length,
        "pitch_min": min(pitches),
        "pitch_max": max(pitches),
        "pitch_span": max(pitches) - min(pitches),
        "pitch_classes": sorted(set(p % 12 for p in pitches)),
        "velocity_min": min(velocities),
        "velocity_max": max(velocities),
        "velocity_mean": round(sum(velocities) / float(len(velocities)), 3),
        "duration_mean": round(sum(durations) / float(len(durations)), 6),
        "last_note_end": round(max(n["start"] + n["dur"] for n in notes), 6),
    }


def _set(ctx, track=0, slot=0, notes=None, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if not clip.is_midi_clip:
        raise ValueError("clip is not a midi clip")
    written = U.write_notes(clip, notes or [])
    return {"written": written}


def _add(ctx, track=0, slot=0, notes=None, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if not clip.is_midi_clip:
        raise ValueError("clip is not a midi clip")
    written = U.write_notes(clip, notes or [], replace=False)
    return {"written": written}


def _clear(ctx, track=0, slot=0, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if not clip.is_midi_clip:
        raise ValueError("clip is not a midi clip")
    clip.remove_notes_extended(0, 128, 0.0, float(clip.length))
    return {"cleared": True}


def _transform(ctx, track, slot, fn):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if not clip.is_midi_clip:
        raise ValueError("clip is not a midi clip")
    notes = U.read_notes(clip)
    fn(notes)
    written = U.write_notes(clip, notes)
    return {"written": written}


def _transpose(ctx, track=0, slot=0, semitones=0, **kw):
    shift = U.as_int(semitones, 0)

    def apply(notes):
        for note in notes:
            note["pitch"] = max(0, min(127, note["pitch"] + shift))

    return _transform(ctx, track, slot, apply)


def _velocity(ctx, track=0, slot=0, factor=1.0, offset=0, **kw):
    scale = U.as_float(factor, 1.0)
    delta = U.as_int(offset, 0)

    def apply(notes):
        for note in notes:
            note["vel"] = max(1, min(127, int(note["vel"] * scale) + delta))

    return _transform(ctx, track, slot, apply)


def _length_scale(ctx, track=0, slot=0, factor=1.0, **kw):
    scale = U.as_float(factor, 1.0)

    def apply(notes):
        for note in notes:
            note["dur"] = max(0.01, note["dur"] * scale)

    return _transform(ctx, track, slot, apply)


def _range(ctx, track=0, slot=0, low=0, high=127, fold=True, **kw):
    floor = U.as_int(low, 0)
    ceiling = U.as_int(high, 127)
    folding = U.as_bool(fold, True) and ceiling - floor >= 11

    def apply(notes):
        for note in notes:
            pitch = note["pitch"]
            if folding:
                while pitch < floor:
                    pitch += 12
                while pitch > ceiling:
                    pitch -= 12
            else:
                pitch = max(floor, min(ceiling, pitch))
            note["pitch"] = max(0, min(127, pitch))

    return _transform(ctx, track, slot, apply)


def _quantize(ctx, track=0, slot=0, grid=0.25, strength=1.0, **kw):
    step = max(0.0001, U.as_float(grid, 0.25))
    amount = U.clamp(strength, 0.0, 1.0)

    def apply(notes):
        for note in notes:
            snapped = round(note["start"] / step) * step
            note["start"] = max(0.0, note["start"] + (snapped - note["start"]) * amount)

    return _transform(ctx, track, slot, apply)


def _humanize(ctx, track=0, slot=0, timing=0.02, velocity=12, seed=0, **kw):
    rng = random.Random(U.as_int(seed, 0))
    jitter_time = abs(U.as_float(timing, 0.02))
    jitter_velocity = abs(U.as_int(velocity, 12))

    def apply(notes):
        for note in notes:
            note["start"] = max(0.0, note["start"] + rng.uniform(-jitter_time, jitter_time))
            note["vel"] = max(1, min(127, note["vel"] + rng.randint(-jitter_velocity, jitter_velocity)))

    return _transform(ctx, track, slot, apply)


def _legato(ctx, track=0, slot=0, gap=0.0, **kw):
    spacing = max(0.0, U.as_float(gap, 0.0))

    def apply(notes):
        notes.sort(key=lambda n: (n["start"], n["pitch"]))
        for index in range(len(notes) - 1):
            current = notes[index]
            following = notes[index + 1]
            current["dur"] = max(0.01, following["start"] - current["start"] - spacing)

    return _transform(ctx, track, slot, apply)


def _shuffle_time(ctx, track=0, slot=0, amount=0.15, seed=0, **kw):
    rng = random.Random(U.as_int(seed, 0))
    spread = U.clamp(amount, 0.0, 1.0)

    def apply(notes):
        notes.sort(key=lambda n: n["start"])
        for note in notes:
            beat = note["start"] % 1.0
            offset = 0.0
            if beat < 0.5:
                offset = -spread * (0.5 - beat) * 0.25
            else:
                offset = spread * (beat - 0.5) * 0.25
            note["start"] = max(0.0, note["start"] + offset + rng.uniform(-0.005, 0.005))

    return _transform(ctx, track, slot, apply)


# ---------------------------------------------------------------- theory
# Pure functions: no Live access, so they are easy to reason about and test.
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLATS = {"DB": 1, "EB": 3, "GB": 6, "AB": 8, "BB": 10, "CB": 11, "FB": 4}

SCALES = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "melodic_minor": (0, 2, 3, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "pentatonic_major": (0, 2, 4, 7, 9),
    "pentatonic_minor": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
    "chromatic": tuple(range(12)),
}

# Krumhansl-Kessler key profiles
_MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

# MPC-style swing presets: (grid in beats, swing percent)
GROOVES = {
    "straight": (0.25, 50.0),
    "mpc_54": (0.25, 54.0),
    "mpc_58": (0.25, 58.0),
    "mpc_62": (0.25, 62.0),
    "mpc_66": (0.25, 66.0),
    "mpc_71": (0.25, 71.0),
    "eighth_swing": (0.5, 62.0),
    "triplet_eighth": (0.5, 66.67),
    "house_shuffle": (0.25, 56.0),
    "hiphop_lazy": (0.25, 64.0),
}


def note_name(pitch):
    """MIDI pitch -> name in Ableton's convention (60 = C3)."""
    return "%s%d" % (NOTE_NAMES[pitch % 12], pitch // 12 - 2)


def parse_root(root):
    """'C', 'F#', 'Bb', 'a' or a 0-11 integer -> pitch class."""
    if isinstance(root, (int, float)):
        return int(root) % 12
    text = str(root).strip().upper()
    if text.lstrip("-").isdigit():
        return int(text) % 12
    if text in _FLATS:
        return _FLATS[text]
    if text in NOTE_NAMES:
        return NOTE_NAMES.index(text)
    raise ValueError("unknown root %r (use C, C#, Db ... or 0-11)" % (root,))


def scale_intervals(scale):
    key = str(scale or "minor").strip().lower().replace(" ", "_").replace("-", "_")
    if key not in SCALES:
        raise ValueError("unknown scale %r (known: %s)" % (scale, ", ".join(sorted(SCALES))))
    return SCALES[key]


def snap_to_scale(pitch, root_pc, intervals, direction="nearest"):
    allowed = set((root_pc + i) % 12 for i in intervals)
    if pitch % 12 in allowed:
        return pitch
    for distance in range(1, 12):
        down, up = pitch - distance, pitch + distance
        if direction in ("nearest", "down") and down % 12 in allowed and down >= 0:
            return down
        if direction in ("nearest", "up") and up % 12 in allowed and up <= 127:
            return up
    return pitch


def chord_pitches(root_pc, intervals, degree, octave=3, size=3, inversion=0, spread=False):
    """Stacked-thirds chord on a 1-based scale degree, as MIDI pitches.

    Octaves follow Ableton's naming, where MIDI note 60 is C3.
    """
    count = len(intervals)
    base = (octave + 2) * 12 + root_pc
    index = U.as_int(degree, 1) - 1
    pitches = []
    for step in range(max(1, min(7, U.as_int(size, 3)))):
        position = index + step * 2
        pitches.append(base + intervals[position % count] + 12 * (position // count))
    for _ in range(max(0, U.as_int(inversion, 0)) % len(pitches)):
        pitches.append(pitches.pop(0) + 12)
    if spread and len(pitches) >= 3:
        pitches[1] += 12
    return [max(0, min(127, p)) for p in sorted(pitches)]


def detect_key(notes):
    """Krumhansl-Schmuckler key estimate weighted by note duration."""
    weights = [0.0] * 12
    for note in notes:
        weights[note["pitch"] % 12] += max(0.01, note["dur"])
    if not any(weights):
        return []
    mean_w = sum(weights) / 12.0

    def correlate(profile, shift):
        rotated = [profile[(pc - shift) % 12] for pc in range(12)]
        mean_p = sum(rotated) / 12.0
        num = sum((w - mean_w) * (p - mean_p) for w, p in zip(weights, rotated))
        den_w = sum((w - mean_w) ** 2 for w in weights) ** 0.5
        den_p = sum((p - mean_p) ** 2 for p in rotated) ** 0.5
        return num / (den_w * den_p) if den_w and den_p else 0.0

    ranked = []
    for pc in range(12):
        ranked.append((correlate(_MAJOR_PROFILE, pc), NOTE_NAMES[pc], "major"))
        ranked.append((correlate(_MINOR_PROFILE, pc), NOTE_NAMES[pc], "minor"))
    ranked.sort(reverse=True)
    return [{"root": name, "scale": scale, "score": round(score, 4)}
            for score, name, scale in ranked]


def _midi_clip(ctx, track, slot):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if not clip.is_midi_clip:
        raise ValueError("clip is not a midi clip")
    return clip


def _scale_fit(ctx, track=0, slot=0, root="C", scale="minor", direction="nearest", **kw):
    root_pc = parse_root(root)
    intervals = scale_intervals(scale)
    if direction not in ("nearest", "up", "down"):
        raise ValueError("direction must be nearest, up or down")
    moved = [0]

    def apply(notes):
        for note in notes:
            snapped = snap_to_scale(note["pitch"], root_pc, intervals, direction)
            if snapped != note["pitch"]:
                moved[0] += 1
                note["pitch"] = snapped

    result = _transform(ctx, track, slot, apply)
    result.update({"moved": moved[0], "root": NOTE_NAMES[root_pc], "scale": scale})
    return result


def _chords(ctx, track=0, slot=0, root="C", scale="minor", progression=None,
            octave=3, size=3, beats_per_chord=4.0, velocity=96, inversions=None,
            spread=False, replace=True, **kw):
    clip = _midi_clip(ctx, track, slot)
    root_pc = parse_root(root)
    intervals = scale_intervals(scale)
    degrees = [U.as_int(d, 1) for d in (progression or [1, 6, 3, 7])]
    span = max(0.25, U.as_float(beats_per_chord, 4.0))
    inversions = list(inversions or [])
    vel = max(1, min(127, U.as_int(velocity, 96)))
    notes, chords = [], []
    for position, degree in enumerate(degrees):
        start = position * span
        if start >= float(clip.length):
            break
        inversion = inversions[position] if position < len(inversions) else 0
        pitches = chord_pitches(root_pc, intervals, degree, U.as_int(octave, 3),
                                size, inversion, U.as_bool(spread, False))
        chords.append({"degree": degree, "start": start,
                       "notes": [note_name(p) for p in pitches]})
        dur = min(span, float(clip.length) - start)
        notes.extend({"pitch": p, "start": start, "dur": dur, "vel": vel} for p in pitches)
    written = U.write_notes(clip, notes, replace=U.as_bool(replace, True))
    return {"written": written, "root": NOTE_NAMES[root_pc], "scale": scale, "chords": chords}


def _detect_key(ctx, track=0, slot=0, top=3, **kw):
    notes = U.read_notes(_midi_clip(ctx, track, slot))
    ranked = detect_key(notes)
    if not ranked:
        return {"count": 0, "candidates": [], "note": "clip has no notes"}
    return {"count": len(notes), "key": ranked[0],
            "candidates": ranked[:max(1, U.as_int(top, 3))]}


def _swing(ctx, track=0, slot=0, preset=None, grid=0.25, amount=58.0, **kw):
    if preset:
        if preset not in GROOVES:
            raise ValueError("unknown groove preset %r (known: %s)"
                             % (preset, ", ".join(sorted(GROOVES))))
        grid, amount = GROOVES[preset]
    step = max(0.0625, U.as_float(grid, 0.25))
    percent = U.clamp(amount, 50.0, 75.0)
    delay = (percent - 50.0) / 50.0 * step
    moved = [0]

    def apply(notes):
        for note in notes:
            index = note["start"] / step
            nearest = int(round(index))
            # only notes sitting on an off-beat grid line get pushed late
            if nearest % 2 == 1 and abs(index - nearest) < 0.2:
                note["start"] = nearest * step + delay
                moved[0] += 1

    result = _transform(ctx, track, slot, apply)
    result.update({"grid": step, "swing_percent": percent, "moved": moved[0]})
    return result


def _arpeggiate(ctx, track=0, slot=0, rate=0.25, style="up", gate=0.8,
                octaves=1, seed=0, **kw):
    step = max(0.03125, U.as_float(rate, 0.25))
    gate_ratio = U.clamp(gate, 0.05, 1.0)
    octave_count = max(1, min(4, U.as_int(octaves, 1)))
    if style not in ("up", "down", "updown", "random", "played"):
        raise ValueError("style must be up, down, updown, random or played")
    rng = random.Random(U.as_int(seed, 0))

    def apply(notes):
        held = sorted(notes, key=lambda n: (n["start"], n["pitch"]))
        if not held:
            return
        out = []
        end = max(n["start"] + n["dur"] for n in held)
        time = held[0]["start"]
        cursor = 0
        while time < end - 1e-6:
            active = [n for n in held if n["start"] <= time + 1e-6 < n["start"] + n["dur"]]
            if active:
                # "played" keeps the order notes start in; the rest go by pitch
                pool = [n["pitch"] + 12 * o for o in range(octave_count) for n in active]
                if style != "played":
                    pool = sorted(set(pool))
                if style == "down":
                    pool.reverse()
                elif style == "updown" and len(pool) > 2:
                    pool = pool + pool[-2:0:-1]
                if style == "random":
                    pitch = rng.choice(pool)
                else:
                    pitch = pool[cursor % len(pool)]
                velocity = max(n["vel"] for n in active)
                out.append({"pitch": min(127, pitch), "start": round(time, 6),
                            "dur": step * gate_ratio, "vel": velocity, "mute": False})
                cursor += 1
            else:
                cursor = 0
            time += step
        notes[:] = out

    result = _transform(ctx, track, slot, apply)
    result.update({"rate": step, "style": style})
    return result


HANDLERS = {
    "notes_scale_fit": _scale_fit,
    "notes_chords": _chords,
    "notes_detect_key": _detect_key,
    "notes_swing": _swing,
    "notes_arpeggiate": _arpeggiate,
    "notes_get": _get,
    "notes_stats": _stats,
    "notes_set": _set,
    "notes_add": _add,
    "notes_clear": _clear,
    "notes_transpose": _transpose,
    "notes_velocity": _velocity,
    "notes_length_scale": _length_scale,
    "notes_range": _range,
    "notes_quantize": _quantize,
    "notes_humanize": _humanize,
    "notes_legato": _legato,
    "notes_shuffle_time": _shuffle_time,
}
