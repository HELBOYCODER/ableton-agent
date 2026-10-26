# -*- coding: utf-8 -*-
"""Arrangement View: arrangement clips, cue points and a scene auto-arranger.

Times are in beats unless a parameter name says bars. Every LOM call that is
newer than Live 11 is guarded with hasattr() and answers with a reason instead
of raising.
"""

from __future__ import absolute_import, print_function, unicode_literals

from . import hb_util as U


def _unsupported(what, version):
    return {"ok": False, "reason": "%s needs Live %s or newer" % (what, version)}


def _beats_per_bar(song):
    return song.signature_numerator * 4.0 / float(song.signature_denominator)


def _arrangement_clips(track):
    clips = getattr(track, "arrangement_clips", None)
    if clips is None:
        raise ValueError("arrangement clips need Live 11 or newer")
    return sorted(clips, key=lambda c: c.start_time)


def _clip_brief(index, clip):
    return {
        "index": index,
        "name": clip.name,
        "start": round(float(clip.start_time), 6),
        "end": round(float(clip.end_time), 6),
        "length": round(float(clip.length), 6),
        "midi": bool(clip.is_midi_clip),
        "muted": bool(getattr(clip, "muted", False)),
        "looping": bool(getattr(clip, "looping", False)),
    }


def _arrangement_clip_at(song, track, index):
    clips = _arrangement_clips(U.track_at(song, track))
    position = U.as_int(index, 0)
    if position < 0:
        position = len(clips) + position
    if position < 0 or position >= len(clips):
        raise IndexError("arrangement clip index out of range: %s" % (index,))
    return clips[position]


def _find_clip_at_time(track, time):
    for clip in _arrangement_clips(track):
        if abs(float(clip.start_time) - time) < 1e-4:
            return clip
    return None


# ------------------------------------------------------------------- state
def _state(ctx, **kw):
    song = ctx.song_ref
    return {
        "song_length": round(float(getattr(song, "song_length", 0.0)), 6),
        "last_event_time": round(float(getattr(song, "last_event_time", 0.0)), 6),
        "current_time": round(float(song.current_song_time), 6),
        "beats_per_bar": _beats_per_bar(song),
        "playing": bool(song.is_playing),
        "record_mode": bool(getattr(song, "record_mode", False)),
        "overdub": bool(getattr(song, "arrangement_overdub", False)),
        "back_to_arranger": bool(getattr(song, "back_to_arranger", False)),
        "loop": {"enabled": bool(song.loop), "start": song.loop_start,
                 "length": song.loop_length},
        "cues": _cue_rows(song),
    }


def _list(ctx, track=0, **kw):
    target = U.track_at(ctx.song_ref, track)
    clips = _arrangement_clips(target)
    return {"track": U.track_position(ctx.song_ref, target),
            "clips": [_clip_brief(i, c) for i, c in enumerate(clips)]}


def _overview(ctx, **kw):
    song = ctx.song_ref
    rows = []
    for index, track in enumerate(song.tracks):
        clips = getattr(track, "arrangement_clips", None)
        if clips is None:
            return _unsupported("arrangement clips", "11")
        rows.append({"track": index, "name": track.name,
                     "clips": [_clip_brief(i, c) for i, c in
                               enumerate(sorted(clips, key=lambda c: c.start_time))]})
    return {"tracks": rows, "beats_per_bar": _beats_per_bar(song)}


# ----------------------------------------------------------------- editing
def _place(ctx, track=0, slot=0, time=None, bar=None, target_track=None, **kw):
    """Copy a Session clip into the arrangement at a time (beats) or bar (1-based)."""
    song = ctx.song_ref
    source = U.clip_at(song, track, slot)
    dest = U.track_at(song, target_track if target_track is not None else track)
    if not hasattr(dest, "duplicate_clip_to_arrangement"):
        return _unsupported("placing clips in the arrangement", "11")
    position = _resolve_time(song, time, bar)
    dest.duplicate_clip_to_arrangement(source, position)
    placed = _find_clip_at_time(dest, position)
    return {"ok": True, "track": U.track_position(song, dest), "time": position,
            "clip": _clip_brief(_arrangement_clips(dest).index(placed), placed)
            if placed is not None else None}


def _create_midi(ctx, track=0, time=None, bar=None, length=4.0, name=None, **kw):
    song = ctx.song_ref
    target = U.track_at(song, track)
    if not hasattr(target, "create_midi_clip"):
        return _unsupported("creating arrangement MIDI clips", "12")
    position = _resolve_time(song, time, bar)
    clip = target.create_midi_clip(position, max(0.25, U.as_float(length, 4.0)))
    if name:
        clip.name = str(name)
    return {"ok": True, "track": U.track_position(song, target),
            "clip": _clip_brief(_arrangement_clips(target).index(clip), clip)}


def _create_audio(ctx, track=0, file_path="", time=None, bar=None, **kw):
    song = ctx.song_ref
    target = U.track_at(song, track)
    if not hasattr(target, "create_audio_clip"):
        return _unsupported("creating arrangement audio clips", "12")
    if not file_path:
        raise ValueError("file_path is required (absolute path to a wav/aif/mp3)")
    position = _resolve_time(song, time, bar)
    clip = target.create_audio_clip(str(file_path), position)
    return {"ok": True, "track": U.track_position(song, target),
            "clip": _clip_brief(_arrangement_clips(target).index(clip), clip)}


def _delete(ctx, track=0, index=0, **kw):
    song = ctx.song_ref
    target = U.track_at(song, track)
    if not hasattr(target, "delete_clip"):
        return _unsupported("deleting arrangement clips", "12")
    clip = _arrangement_clip_at(song, track, index)
    brief = _clip_brief(U.as_int(index, 0), clip)
    target.delete_clip(clip)
    return {"ok": True, "deleted": brief}


def _notes_get(ctx, track=0, index=0, **kw):
    clip = _arrangement_clip_at(ctx.song_ref, track, index)
    if not clip.is_midi_clip:
        raise ValueError("arrangement clip is not a midi clip")
    notes = U.read_notes(clip)
    return {"notes": notes, "count": len(notes), "clip": _clip_brief(U.as_int(index, 0), clip)}


def _notes_set(ctx, track=0, index=0, notes=None, replace=True, **kw):
    clip = _arrangement_clip_at(ctx.song_ref, track, index)
    if not clip.is_midi_clip:
        raise ValueError("arrangement clip is not a midi clip")
    return {"written": U.write_notes(clip, notes or [], replace=U.as_bool(replace, True))}


# ------------------------------------------------------------- transport
def _record(ctx, enabled=True, overdub=None, **kw):
    song = ctx.song_ref
    song.record_mode = U.as_bool(enabled, True)
    if overdub is not None and hasattr(song, "arrangement_overdub"):
        song.arrangement_overdub = U.as_bool(overdub, False)
    return {"record_mode": bool(song.record_mode),
            "overdub": bool(getattr(song, "arrangement_overdub", False))}


def _back_to_arranger(ctx, **kw):
    song = ctx.song_ref
    if hasattr(song, "back_to_arranger"):
        song.back_to_arranger = False
    return {"back_to_arranger": bool(getattr(song, "back_to_arranger", False))}


def _show(ctx, view="Arranger", **kw):
    name = "Arranger" if str(view).lower().startswith("arr") else "Session"
    try:
        import Live
        app_view = Live.Application.get_application().view
        app_view.show_view(name)
        app_view.focus_view(name)
    except Exception as error:  # view API is cosmetic; never fail hard here
        return {"ok": False, "reason": "%s: %s" % (type(error).__name__, error)}
    return {"ok": True, "view": name}


# ------------------------------------------------------------------- cues
def _cue_rows(song):
    cues = sorted(getattr(song, "cue_points", []) or [], key=lambda c: c.time)
    return [{"index": i, "name": c.name, "time": round(float(c.time), 6)}
            for i, c in enumerate(cues)]


def _cue_at(song, index):
    cues = sorted(song.cue_points, key=lambda c: c.time)
    position = U.as_int(index, 0)
    if position < 0 or position >= len(cues):
        raise IndexError("cue index out of range: %s" % (index,))
    return cues[position]


def _add_cue(song, position, name=None):
    """Create a locator at position (set_or_delete_cue toggles at the playhead)."""
    for cue in song.cue_points:
        if abs(float(cue.time) - position) < 1e-4:
            if name:
                cue.name = str(name)
            return cue
    previous = song.current_song_time
    song.current_song_time = position
    song.set_or_delete_cue()
    song.current_song_time = previous
    for cue in song.cue_points:
        if abs(float(cue.time) - position) < 1e-4:
            if name:
                cue.name = str(name)
            return cue
    return None


def _cue_list(ctx, **kw):
    return {"cues": _cue_rows(ctx.song_ref)}


def _cue_add(ctx, time=None, bar=None, name=None, **kw):
    song = ctx.song_ref
    position = _resolve_time(song, time, bar)
    cue = _add_cue(song, position, name)
    return {"ok": cue is not None, "cues": _cue_rows(song)}


def _cue_jump(ctx, index=0, **kw):
    cue = _cue_at(ctx.song_ref, index)
    cue.jump()
    return {"jumped": cue.name, "time": cue.time}


def _cue_rename(ctx, index=0, name="", **kw):
    cue = _cue_at(ctx.song_ref, index)
    cue.name = str(name)
    return {"index": index, "name": cue.name}


def _cue_delete(ctx, index=0, **kw):
    song = ctx.song_ref
    cue = _cue_at(song, index)
    previous = song.current_song_time
    song.current_song_time = cue.time
    song.set_or_delete_cue()
    song.current_song_time = previous
    return {"cues": _cue_rows(song)}


# ----------------------------------------------------------- auto-arranger
def _resolve_time(song, time=None, bar=None):
    if bar is not None:
        return max(0.0, (U.as_float(bar, 1.0) - 1.0) * _beats_per_bar(song))
    if time is not None:
        return max(0.0, U.as_float(time, 0.0))
    return max(0.0, float(song.current_song_time))


def _from_scenes(ctx, sections=None, start_bar=1, tracks=None, add_cues=True, **kw):
    """Lay scenes out on the timeline.

    sections: [{"scene": 0, "bars": 8, "name": "Intro"}, ...]. Each track's clip
    in that scene is copied in and repeated to fill the section; tracks without
    a clip in the scene stay silent for the section.
    """
    song = ctx.song_ref
    if not song.tracks or not hasattr(song.tracks[0], "duplicate_clip_to_arrangement"):
        return _unsupported("the auto-arranger", "11")
    if not sections:
        raise ValueError("sections is required, e.g. [{\"scene\": 0, \"bars\": 8}]")
    wanted = None if tracks is None else set(U.as_int(t, 0) for t in tracks)
    per_bar = _beats_per_bar(song)
    cursor = (U.as_float(start_bar, 1.0) - 1.0) * per_bar
    layout = []
    placed = 0

    for section in sections:
        scene_index = U.as_int(section.get("scene", 0), 0)
        if scene_index < 0 or scene_index >= len(song.scenes):
            raise IndexError("scene index out of range: %s" % scene_index)
        bars = max(1.0, U.as_float(section.get("bars", 8), 8.0))
        span = bars * per_bar
        name = section.get("name") or song.scenes[scene_index].name or "Scene %d" % (scene_index + 1)
        used_tracks = []
        for index, track in enumerate(song.tracks):
            if wanted is not None and index not in wanted:
                continue
            slots = track.clip_slots
            if scene_index >= len(slots) or not slots[scene_index].has_clip:
                continue
            clip = slots[scene_index].clip
            clip_span = max(0.25, float(clip.length))
            offset = 0.0
            while offset < span - 1e-6:
                track.duplicate_clip_to_arrangement(clip, cursor + offset)
                placed += 1
                offset += clip_span
            used_tracks.append(index)
        if U.as_bool(add_cues, True) and hasattr(song, "set_or_delete_cue"):
            _add_cue(song, cursor, name)
        layout.append({"name": name, "scene": scene_index, "start_bar": cursor / per_bar + 1,
                       "bars": bars, "tracks": used_tracks})
        cursor += span

    return {"ok": True, "sections": layout, "clips_placed": placed,
            "end_bar": cursor / per_bar + 1}


HANDLERS = {
    "arrangement_state": _state,
    "arrangement_overview": _overview,
    "arrangement_clips": _list,
    "arrangement_place_clip": _place,
    "arrangement_create_midi_clip": _create_midi,
    "arrangement_create_audio_clip": _create_audio,
    "arrangement_delete_clip": _delete,
    "arrangement_notes_get": _notes_get,
    "arrangement_notes_set": _notes_set,
    "arrangement_record": _record,
    "arrangement_back_to_arranger": _back_to_arranger,
    "arrangement_show": _show,
    "arrangement_from_scenes": _from_scenes,
    "cue_list": _cue_list,
    "cue_add": _cue_add,
    "cue_jump": _cue_jump,
    "cue_rename": _cue_rename,
    "cue_delete": _cue_delete,
}
