# -*- coding: utf-8 -*-
"""Clip slots, clips and scenes."""

from __future__ import absolute_import, print_function, unicode_literals

from . import hb_util as U


def _list(ctx, track=0, **kw):
    target = U.track_at(ctx.song_ref, track)
    slots = []
    for index, slot in enumerate(target.clip_slots):
        entry = {"index": index, "has_clip": bool(slot.has_clip),
                 "fired": bool(slot.is_playing), "stop": bool(slot.is_stop)}
        if slot.has_clip:
            clip = slot.clip
            entry.update({
                "name": clip.name,
                "length": clip.length,
                "midi": bool(clip.is_midi_clip),
                "looping": bool(clip.looping),
                "color_index": clip.color_index,
            })
        slots.append(entry)
    return {"track": track, "slots": slots}


def _info(ctx, track=0, slot=0, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    data = {
        "track": track,
        "slot": slot,
        "name": clip.name,
        "length": clip.length,
        "midi": bool(clip.is_midi_clip),
        "looping": bool(clip.looping),
        "loop_start": clip.loop_start,
        "loop_end": clip.loop_end,
        "color_index": clip.color_index,
        "start_marker": getattr(clip, "start_marker", None),
        "end_marker": getattr(clip, "end_marker", None),
        "warping": bool(getattr(clip, "warping", False)),
        "warp_mode": getattr(clip, "warp_mode", None),
        "gain": getattr(clip, "gain", None),
        "pitch_coarse": getattr(clip, "pitch_coarse", None),
        "file_path": getattr(clip, "file_path", None),
    }
    if clip.is_midi_clip:
        data["note_count"] = len(U.read_notes(clip))
    return data


def _create(ctx, track=0, slot=0, length=4.0, name=None, **kw):
    target = U.clip_slot_at(ctx.song_ref, track, slot)
    if target.has_clip:
        raise ValueError("slot %s on track %s already has a clip" % (slot, track))
    clip = target.create_clip(U.as_float(length, 4.0))
    if name:
        clip.name = str(name)
    return {"track": track, "slot": slot, "length": clip.length, "name": clip.name}


def _delete(ctx, track=0, slot=0, **kw):
    target = U.clip_slot_at(ctx.song_ref, track, slot)
    if not target.has_clip:
        raise ValueError("slot %s on track %s is empty" % (slot, track))
    target.delete_clip()
    return {"deleted": True, "track": track, "slot": slot}


def _duplicate(ctx, track=0, slot=0, target_track=None, target_slot=None, **kw):
    song = ctx.song_ref
    source = U.clip_slot_at(song, track, slot)
    if not source.has_clip:
        raise ValueError("source slot is empty")
    dest_track = U.track_at(song, target_track if target_track is not None else track)
    dest_slot = dest_track.clip_slots[U.as_int(target_slot, slot)]
    if dest_slot.has_clip:
        dest_slot.delete_clip()
    source.duplicate_clip_to(dest_slot)
    return {"duplicated_to": [U.track_position(song, dest_track),
                              U.as_int(target_slot, slot)]}


def _rename(ctx, track=0, slot=0, name="", **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    clip.name = str(name)
    return {"name": clip.name}


def _color(ctx, track=0, slot=0, color_index=0, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    clip.color_index = max(0, min(69, U.as_int(color_index, 0)))
    return {"color_index": clip.color_index}


def _set_loop(ctx, track=0, slot=0, start=None, end=None, looping=None, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if looping is not None:
        clip.looping = U.as_bool(looping, True)
    if start is not None:
        clip.loop_start = max(0.0, U.as_float(start, 0.0))
    if end is not None:
        clip.loop_end = max(clip.loop_start, U.as_float(end, clip.length))
    return {"looping": bool(clip.looping),
            "loop_start": clip.loop_start,
            "loop_end": clip.loop_end}


def _set_markers(ctx, track=0, slot=0, start=None, end=None, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if start is not None and hasattr(clip, "start_marker"):
        clip.start_marker = max(0.0, U.as_float(start, 0.0))
    if end is not None and hasattr(clip, "end_marker"):
        clip.end_marker = max(0.0, U.as_float(end, clip.length))
    return {"start_marker": getattr(clip, "start_marker", None),
            "end_marker": getattr(clip, "end_marker", None)}


def _set_warp(ctx, track=0, slot=0, warping=None, mode=None, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if hasattr(clip, "warping") and warping is not None:
        clip.warping = U.as_bool(warping, True)
    if hasattr(clip, "warp_mode") and mode is not None:
        clip.warp_mode = U.as_int(mode, 0)
    return {"warping": getattr(clip, "warping", None),
            "warp_mode": getattr(clip, "warp_mode", None)}


def _fire(ctx, track=0, slot=0, **kw):
    U.clip_slot_at(ctx.song_ref, track, slot).fire()
    return {"fired": [track, slot]}


def _stop(ctx, track=0, slot=0, **kw):
    U.clip_slot_at(ctx.song_ref, track, slot).stop()
    return {"stopped": [track, slot]}


def _transpose_clip(ctx, track=0, slot=0, semitones=0, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    if not clip.is_midi_clip:
        return {"ok": False, "reason": "not a midi clip"}
    notes = U.read_notes(clip)
    shift = U.as_int(semitones, 0)
    for note in notes:
        note["pitch"] = max(0, min(127, note["pitch"] + shift))
    written = U.write_notes(clip, notes)
    return {"written": written, "semitones": shift}


# --------------------------------------------------------------------- scenes
def _scene_list(ctx, **kw):
    return {"scenes": [{"index": i, "name": s.name,
                        "tempo": getattr(s, "tempo", None)}
                       for i, s in enumerate(ctx.song_ref.scenes)]}


def _scene_create(ctx, index=-1, name=None, **kw):
    song = ctx.song_ref
    song.create_scene(U.as_int(index, -1))
    scene = song.scenes[U.as_int(index, -1)]
    if name:
        scene.name = str(name)
    return {"index": U.as_int(index, -1), "name": scene.name}


def _scene_delete(ctx, index=0, **kw):
    song = ctx.song_ref
    song.delete_scene(U.as_int(index, 0))
    return {"scene_count": len(song.scenes)}


def _scene_fire(ctx, index=0, **kw):
    ctx.song_ref.scenes[U.as_int(index, 0)].fire()
    return {"fired": U.as_int(index, 0)}


def _scene_rename(ctx, index=0, name="", **kw):
    scene = ctx.song_ref.scenes[U.as_int(index, 0)]
    scene.name = str(name)
    return {"index": index, "name": scene.name}


def _scene_duplicate(ctx, index=0, **kw):
    song = ctx.song_ref
    song.duplicate_scene(U.as_int(index, 0))
    return {"scene_count": len(song.scenes)}


HANDLERS = {
    "clip_list": _list,
    "clip_info": _info,
    "clip_create": _create,
    "clip_delete": _delete,
    "clip_duplicate": _duplicate,
    "clip_rename": _rename,
    "clip_color": _color,
    "clip_set_loop": _set_loop,
    "clip_set_markers": _set_markers,
    "clip_set_warp": _set_warp,
    "clip_fire": _fire,
    "clip_stop": _stop,
    "clip_transpose": _transpose_clip,
    "scene_list": _scene_list,
    "scene_create": _scene_create,
    "scene_delete": _scene_delete,
    "scene_fire": _scene_fire,
    "scene_rename": _scene_rename,
    "scene_duplicate": _scene_duplicate,
}
