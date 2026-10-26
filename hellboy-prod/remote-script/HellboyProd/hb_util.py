# -*- coding: utf-8 -*-
"""Shared helpers for the Hellboy Prod remote script.

Pure, dependency-free utilities used by every hb_*.py handler module:
value coercion, index resolution against the Live Object Model, and the
MIDI note read/write bridge. Note dicts use the compact wire shape
``{"pitch", "start", "dur", "vel", "mute"}``.
"""

from __future__ import absolute_import, print_function, unicode_literals

try:
    import Live
except ImportError:  # pragma: no cover - only importable inside Live
    Live = None


# A unique sentinel a handler returns to say "do not reply yet; the answer
# will be delivered later through ctx.reply_later()".
DEFERRED = object()


# --------------------------------------------------------------------- coercion
def as_int(value, default=0):
    try:
        if value is None:
            return int(default)
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)


def as_float(value, default=0.0):
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def as_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "y", "t"):
        return True
    if text in ("0", "false", "no", "off", "n", "f", ""):
        return False
    return bool(default)


def clamp(value, low, high):
    number = as_float(value, low)
    if number < low:
        return low
    if number > high:
        return high
    return number


def norm(value):
    """Clamp an arbitrary value into the Live normalized 0.0 - 1.0 range."""
    return clamp(value, 0.0, 1.0)


# ------------------------------------------------------------------ resolution
def track_at(song, index):
    tracks = song.tracks
    position = as_int(index, 0)
    if position < 0:
        position = len(tracks) + position
    if position < 0 or position >= len(tracks):
        raise IndexError("track index out of range: %s" % (index,))
    return tracks[position]


def track_position(song, track):
    for index, candidate in enumerate(song.tracks):
        if candidate == track:
            return index
    raise ValueError("track is not in the song track list")


def clip_slot_at(song, track, slot):
    target = track_at(song, track)
    slots = target.clip_slots
    position = as_int(slot, 0)
    if position < 0:
        position = len(slots) + position
    if position < 0 or position >= len(slots):
        raise IndexError("clip slot index out of range: %s" % (slot,))
    return slots[position]


def clip_at(song, track, slot):
    target = clip_slot_at(song, track, slot)
    if not target.has_clip:
        raise ValueError("no clip at track %s slot %s" % (track, slot))
    return target.clip


def device_at(track, index):
    devices = track.devices
    position = as_int(index, 0)
    if position < 0:
        position = len(devices) + position
    if position < 0 or position >= len(devices):
        raise IndexError("device index out of range: %s" % (index,))
    return devices[position]


def parameter_at(unit, index=None, name=None):
    parameters = list(unit.parameters)
    if name:
        for parameter in parameters:
            if parameter.name == name:
                return parameter
        raise ValueError("no parameter named %r on %s" % (name, unit.name))
    position = as_int(index, 0)
    if position < 0:
        position = len(parameters) + position
    if position < 0 or position >= len(parameters):
        raise IndexError("parameter index out of range: %s" % (index,))
    return parameters[position]


# ----------------------------------------------------------------------- views
def track_brief(song, index, track):
    mixer = track.mixer_device
    has_midi = bool(getattr(track, "has_midi_input", False))
    sends = []
    try:
        sends = [round(send.value, 6) for send in mixer.sends]
    except Exception:
        sends = []
    clip_count = 0
    try:
        clip_count = sum(1 for slot in track.clip_slots if slot.has_clip)
    except Exception:
        clip_count = 0
    return {
        "index": index,
        "name": track.name,
        "kind": "midi" if has_midi else "audio",
        "color_index": getattr(track, "color_index", None),
        "mute": bool(getattr(track, "mute", False)),
        "solo": bool(getattr(track, "solo", False)),
        "arm": bool(getattr(track, "arm", False)) if getattr(track, "can_be_armed", False) else False,
        "volume": round(mixer.volume.value, 6),
        "pan": round(mixer.panning.value, 6),
        "grouped": bool(getattr(track, "is_grouped", False)),
        "device_count": len(track.devices),
        "clip_count": clip_count,
        "sends": sends,
    }


def device_brief(index, device):
    return {
        "index": index,
        "name": device.name,
        "class": getattr(device, "class_name", None),
        "active": bool(getattr(device, "is_active", True)),
        "chainable": bool(getattr(device, "can_have_chains", False)),
        "parameter_count": len(device.parameters),
    }


def parameter_brief(index, parameter):
    return {
        "index": index,
        "name": parameter.name,
        "value": round(float(parameter.value), 6),
        "min": round(float(parameter.min), 6),
        "max": round(float(parameter.max), 6),
        "quantized": bool(getattr(parameter, "is_quantized", False)),
        "display": getattr(parameter, "display_value", None) and str(parameter.display_value) or None,
    }


# ------------------------------------------------------------------- midi notes
def read_notes(clip, pitch_low=0, pitch_high=127, time_low=0.0, time_high=None):
    low = as_int(pitch_low, 0)
    high = as_int(pitch_high, 127)
    pitch_span = max(1, high - low + 1)
    start = as_float(time_low, 0.0)
    if time_high is None:
        span = float(clip.length)
    else:
        span = max(0.0, as_float(time_high, clip.length) - start)

    out = []
    getter = getattr(clip, "get_notes_extended", None)
    if callable(getter):
        for note in getter(low, pitch_span, start, span):
            out.append({
                "pitch": int(note.pitch),
                "start": round(float(note.start_time), 6),
                "dur": round(float(note.duration), 6),
                "vel": int(round(float(note.velocity))),
                "mute": bool(note.mute),
            })
        return out

    # Legacy Live 9/10 fallback: (pitch, start, duration, velocity, mute) tuples
    legacy = getattr(clip, "get_notes", None)
    if callable(legacy):
        for pitch, note_start, duration, velocity, mute in legacy(start, low, span, pitch_span):
            out.append({
                "pitch": int(pitch),
                "start": round(float(note_start), 6),
                "dur": round(float(duration), 6),
                "vel": int(round(float(velocity))),
                "mute": bool(mute),
            })
    return out


def write_notes(clip, notes, replace=True):
    notes = list(notes or [])
    if replace:
        remover = getattr(clip, "remove_notes_extended", None)
        if callable(remover):
            remover(0, 128, 0.0, float(clip.length))
        elif hasattr(clip, "select_all_notes"):
            clip.select_all_notes()
            clip.replace_selected_notes(tuple())

    adder = getattr(clip, "add_new_notes", None)
    if callable(adder) and Live is not None and hasattr(Live.Clip, "MidiNoteSpecification"):
        specs = tuple(
            Live.Clip.MidiNoteSpecification(
                pitch=max(0, min(127, as_int(note.get("pitch", 60), 60))),
                start_time=max(0.0, as_float(note.get("start", 0.0), 0.0)),
                duration=max(0.001, as_float(note.get("dur", 0.25), 0.25)),
                velocity=max(1, min(127, as_int(note.get("vel", 100), 100))),
                mute=as_bool(note.get("mute", False), False),
            )
            for note in notes
        )
        if specs:
            adder(specs)
        return len(notes)

    # Legacy Live 9/10 fallback via set_notes(tuple of tuples)
    legacy = getattr(clip, "set_notes", None)
    if callable(legacy):
        packed = tuple(
            (
                max(0, min(127, as_int(note.get("pitch", 60), 60))),
                max(0.0, as_float(note.get("start", 0.0), 0.0)),
                max(0.001, as_float(note.get("dur", 0.25), 0.25)),
                max(1, min(127, as_int(note.get("vel", 100), 100))),
                as_bool(note.get("mute", False), False),
            )
            for note in notes
        )
        clip.set_notes(packed)
    return len(notes)
