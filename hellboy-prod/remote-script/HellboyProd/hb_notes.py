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


HANDLERS = {
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
