# -*- coding: utf-8 -*-
"""Quick Loop + Shuffle - slice a clip and rebuild it in a new order."""

from __future__ import absolute_import, print_function, unicode_literals

import random

from . import hb_util as U


def _destination(song, track, slot, target_track, target_slot):
    source_track = U.track_at(song, track)
    source_slot = U.clip_slot_at(song, track, slot)
    dest_track = U.track_at(song, target_track if target_track is not None else track)
    slots = list(dest_track.clip_slots)
    if target_slot is None:
        # default: first empty slot after the source slot on the destination track
        start = U.as_int(slot, 0) + 1 if dest_track == source_track else 0
        position = next((i for i in range(max(0, start), len(slots))
                         if not slots[i].has_clip), None)
        if position is None:
            raise ValueError("no empty clip slot on the destination track - pass target_slot")
    else:
        position = U.as_int(target_slot, 0)
        if position < 0:
            position = len(slots) + position
    if position < 0 or position >= len(slots):
        raise IndexError("destination slot out of range: %s" % target_slot)
    if slots[position] == source_slot:
        raise ValueError("destination is the source clip slot - choose another target_slot")
    return dest_track, slots[position], position


def _generate(ctx, track=0, slot=0, target_track=None, target_slot=None,
              seed=0, slices=8, transpose=0, mode="shuffle",
              velocity_jitter=0, **kw):
    song = ctx.song_ref
    source = U.clip_at(song, track, slot)
    rng = random.Random(U.as_int(seed, 0))
    slice_count = max(1, min(64, U.as_int(slices, 8)))
    transpose_span = abs(U.as_int(transpose, 0))
    jitter = abs(U.as_int(velocity_jitter, 0))

    dest_track, dest_slot, dest_index = _destination(song, track, slot, target_track, target_slot)
    dest_track_index = U.track_position(song, dest_track)

    if source.is_midi_clip:
        result = _shuffle_midi(song, source, dest_slot, rng, slice_count,
                               transpose_span, jitter, mode)
    else:
        result = _shuffle_audio(song, source, dest_slot, rng, slice_count, mode)

    result.update({
        "source": [U.track_position(song, U.track_at(song, track)), U.as_int(slot, 0)],
        "destination": [dest_track_index, dest_index],
        "mode": mode,
        "seed": U.as_int(seed, 0),
    })
    return result


def _shuffle_midi(song, source, dest_slot, rng, slice_count, transpose_span,
                  jitter, mode):
    length = float(source.length)
    if dest_slot.has_clip:
        dest_slot.delete_clip()
    target = dest_slot.create_clip(length)
    target.name = "%s [shuffled]" % (source.name or "loop")

    notes = U.read_notes(source)
    if not notes:
        return {"notes": 0, "length": length}

    slice_length = length / float(slice_count)
    order = list(range(slice_count))
    if mode == "reverse":
        order.reverse()
    elif mode == "rotate":
        shift = rng.randrange(slice_count)
        order = order[shift:] + order[:shift]
    else:
        rng.shuffle(order)

    out = []
    for new_slice, old_slice in enumerate(order):
        offset = (new_slice - old_slice) * slice_length
        for note in notes:
            if old_slice * slice_length <= note["start"] < (old_slice + 1) * slice_length:
                start = note["start"] + offset
                pitch = note["pitch"]
                if transpose_span:
                    pitch += rng.randint(-transpose_span, transpose_span)
                velocity = note["vel"]
                if jitter:
                    velocity += rng.randint(-jitter, jitter)
                out.append({
                    "pitch": max(0, min(127, pitch)),
                    "start": max(0.0, min(length - 0.01, start)),
                    "dur": min(note["dur"], max(0.02, length - start)),
                    "vel": max(1, min(127, velocity)),
                    "mute": note["mute"],
                })
    written = U.write_notes(target, out)
    return {"notes": written, "length": length, "slices": slice_count}


def _shuffle_audio(song, source, dest_slot, rng, slice_count, mode):
    length = float(source.length)
    if dest_slot.has_clip:
        dest_slot.delete_clip()
    source.duplicate_clip_to(dest_slot)
    target = dest_slot.clip
    target.name = "%s [shuffled]" % (source.name or "loop")

    try:
        slice_length = length / float(slice_count)
        start = rng.randrange(slice_count) * slice_length
        target.loop_start = max(0.0, start)
        target.loop_end = min(length, start + slice_length)
        target.looping = True
        if hasattr(target, "start_marker"):
            target.start_marker = target.loop_start
    except Exception:
        pass
    return {"length": length, "slices": slice_count,
            "loop_start": getattr(target, "loop_start", None),
            "loop_end": getattr(target, "loop_end", None)}


def _scatter(ctx, track=0, slot=0, target_track=None, target_slot=None, seed=0, **kw):
    return _generate(ctx, track=track, slot=slot, target_track=target_track,
                     target_slot=target_slot, seed=seed, slices=16, transpose=12, mode="shuffle",
                     velocity_jitter=18)


HANDLERS = {
    "quickloop_generate": _generate,
    "quickloop_scatter": _scatter,
}
