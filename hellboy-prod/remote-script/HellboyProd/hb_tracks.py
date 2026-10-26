# -*- coding: utf-8 -*-
"""Track creation, routing and mixer control."""

from __future__ import absolute_import, print_function, unicode_literals

from . import hb_util as U


def _list(ctx, **kw):
    song = ctx.song_ref
    return {"tracks": [U.track_brief(song, i, t) for i, t in enumerate(song.tracks)]}


def _brief(ctx, index=0, **kw):
    song = ctx.song_ref
    track = U.track_at(song, index)
    data = U.track_brief(song, U.track_position(song, track), track)
    data["devices"] = [U.device_brief(i, d) for i, d in enumerate(track.devices)]
    data["slots"] = [
        {"index": i, "has_clip": bool(s.has_clip),
         "name": s.clip.name if s.has_clip else None}
        for i, s in enumerate(track.clip_slots)
    ]
    return data


def _create_midi(ctx, index=-1, name=None, **kw):
    song = ctx.song_ref
    song.create_midi_track(U.as_int(index, -1))
    track = song.tracks[U.as_int(index, -1)]
    if name:
        track.name = str(name)
    return {"index": U.track_position(song, track), "name": track.name}


def _create_audio(ctx, index=-1, name=None, **kw):
    song = ctx.song_ref
    song.create_audio_track(U.as_int(index, -1))
    track = song.tracks[U.as_int(index, -1)]
    if name:
        track.name = str(name)
    return {"index": U.track_position(song, track), "name": track.name}


def _create_return(ctx, name=None, **kw):
    song = ctx.song_ref
    song.create_return_track()
    track = song.return_tracks[-1]
    if name:
        track.name = str(name)
    return {"index": len(song.return_tracks) - 1, "name": track.name}


def _delete(ctx, index=0, **kw):
    song = ctx.song_ref
    position = U.track_position(song, U.track_at(song, index))
    song.delete_track(position)
    return {"deleted": position, "track_count": len(song.tracks)}


def _duplicate(ctx, index=0, **kw):
    song = ctx.song_ref
    position = U.track_position(song, U.track_at(song, index))
    song.duplicate_track(position)
    return {"duplicated": position, "track_count": len(song.tracks)}


def _rename(ctx, index=0, name="", **kw):
    track = U.track_at(ctx.song_ref, index)
    track.name = str(name)
    return {"index": index, "name": track.name}


def _color(ctx, index=0, color_index=0, **kw):
    track = U.track_at(ctx.song_ref, index)
    track.color_index = max(0, min(69, U.as_int(color_index, 0)))
    return {"index": index, "color_index": track.color_index}


def _set_volume(ctx, index=0, value=0.85, **kw):
    track = U.track_at(ctx.song_ref, index)
    track.mixer_device.volume.value = U.norm(value)
    return {"index": index, "volume": track.mixer_device.volume.value}


def _set_pan(ctx, index=0, value=0.0, **kw):
    track = U.track_at(ctx.song_ref, index)
    pan = track.mixer_device.panning
    track.mixer_device.panning.value = max(pan.min, min(pan.max, U.as_float(value, 0.0)))
    return {"index": index, "pan": track.mixer_device.panning.value}


def _mute(ctx, index=0, value=True, **kw):
    track = U.track_at(ctx.song_ref, index)
    track.mute = U.as_bool(value, True)
    return {"index": index, "mute": bool(track.mute)}


def _solo(ctx, index=0, value=True, **kw):
    track = U.track_at(ctx.song_ref, index)
    track.solo = U.as_bool(value, True)
    return {"index": index, "solo": bool(track.solo)}


def _arm(ctx, index=0, value=True, **kw):
    track = U.track_at(ctx.song_ref, index)
    if track.can_be_armed:
        track.arm = U.as_bool(value, True)
    return {"index": index, "arm": bool(track.arm)}


def _set_send(ctx, index=0, send=0, value=0.0, **kw):
    track = U.track_at(ctx.song_ref, index)
    sends = list(track.mixer_device.sends)
    position = U.as_int(send, 0)
    if position < 0 or position >= len(sends):
        raise IndexError("send index out of range: %s" % send)
    sends[position].value = U.norm(value)
    return {"index": index, "send": position, "value": sends[position].value}


def _select(ctx, index=0, **kw):
    song = ctx.song_ref
    track = U.track_at(song, index)
    song.view.selected_track = track
    return {"selected": U.track_position(song, track)}


def _group(ctx, indices=None, **kw):
    song = ctx.song_ref
    creator = getattr(song, "create_group_track", None)
    if not callable(creator):
        return {"ok": False, "reason": "create_group_track not exposed by this Live version"}
    requested = [U.as_int(i, 0) for i in (indices or [0])]
    anchor = max(0, min(requested))
    creator(anchor)
    return {"ok": True, "index": anchor, "track_count": len(song.tracks)}


def _move(ctx, index=0, to=0, **kw):
    song = ctx.song_ref
    track = U.track_at(song, index)
    mover = getattr(song, "move_track", None)
    if not callable(mover):
        return {"ok": False, "reason": "move_track not exposed by this Live version"}
    mover(track, U.as_int(to, 0))
    return {"ok": True, "index": U.as_int(to, 0)}


def _fold(ctx, index=0, folded=True, **kw):
    track = U.track_at(ctx.song_ref, index)
    if not getattr(track, "is_foldable", False):
        return {"ok": False, "reason": "only group tracks can be folded"}
    track.fold_state = U.as_bool(folded, True)
    return {"ok": True, "index": index, "folded": bool(track.fold_state)}


def _set_frozen(ctx, index, frozen):
    track = U.track_at(ctx.song_ref, index)
    if frozen and not getattr(track, "can_be_frozen", False):
        return {"ok": False, "reason": "track cannot be frozen"}
    try:
        track.is_frozen = frozen
    except (AttributeError, RuntimeError):
        # is_frozen is read-only in the Live Object Model of current versions
        return {"ok": False, "is_frozen": bool(getattr(track, "is_frozen", False)),
                "reason": "this Live version does not allow scripts to (un)freeze; "
                          "use Freeze Track in the track context menu"}
    return {"ok": True, "index": index, "is_frozen": bool(track.is_frozen)}


def _freeze(ctx, index=0, **kw):
    return _set_frozen(ctx, index, True)


def _unfreeze(ctx, index=0, **kw):
    return _set_frozen(ctx, index, False)


HANDLERS = {
    "track_list": _list,
    "track_brief": _brief,
    "track_create_midi": _create_midi,
    "track_create_audio": _create_audio,
    "track_create_return": _create_return,
    "track_delete": _delete,
    "track_duplicate": _duplicate,
    "track_rename": _rename,
    "track_color": _color,
    "track_set_volume": _set_volume,
    "track_set_pan": _set_pan,
    "track_mute": _mute,
    "track_solo": _solo,
    "track_arm": _arm,
    "track_set_send": _set_send,
    "track_select": _select,
    "track_group": _group,
    "track_move": _move,
    "track_fold": _fold,
    "track_freeze": _freeze,
    "track_unfreeze": _unfreeze,
}
