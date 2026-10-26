# -*- coding: utf-8 -*-
"""Mix reporting and an automatic balance pass (deferred sampling)."""

from __future__ import absolute_import, print_function, unicode_literals

from . import hb_util as U


def _levels(song, indices=None):
    out = []
    for index, track in enumerate(song.tracks):
        if indices is not None and index not in indices:
            continue
        if not track.has_audio_output:
            continue
        left = float(track.output_meter_left)
        right = float(track.output_meter_right)
        out.append((index, track, max(left, right)))
    return out


def _report(ctx, tracks=None, include_meters=True, **kw):
    song = ctx.song_ref
    wanted = None if tracks is None else set(U.as_int(t, 0) for t in tracks)
    rows = []
    for index, track, level in _levels(song, wanted):
        rows.append({
            "index": index,
            "name": track.name,
            "kind": "midi" if track.has_midi_input else "audio",
            "volume": round(track.mixer_device.volume.value, 6),
            "pan": round(track.mixer_device.panning.value, 6),
            "mute": bool(track.mute),
            "solo": bool(track.solo),
            "device_count": len(track.devices),
            "meter": round(level, 6) if include_meters else None,
            "sends": [round(s.value, 6) for s in track.mixer_device.sends],
        })
    rows.sort(key=lambda row: (-(row["meter"] or 0.0), row["index"]))
    loudest = rows[0]["meter"] if rows else 0.0
    return {
        "tracks": rows,
        "loudest_meter": loudest,
        "master_volume": song.master_track.mixer_device.volume.value,
        "playing": bool(song.is_playing),
        "note": "meters are instantaneous - start transport for a meaningful read",
    }


def _balance(ctx, target=0.7, tracks=None, samples=6, interval=2,
             max_gain=4.0, min_gain=0.25, **kw):
    song = ctx.song_ref
    wanted = None if tracks is None else set(U.as_int(t, 0) for t in tracks)
    state = {"collected": 0, "accumulator": {}}

    def collect():
        for index, _track, level in _levels(song, wanted):
            state["accumulator"].setdefault(index, []).append(level)
        state["collected"] += 1
        if state["collected"] < max(1, U.as_int(samples, 6)):
            ctx.schedule_message(max(1, U.as_int(interval, 2)), collect)
            return
        ctx.reply_later(lambda: _apply(song, state["accumulator"], target,
                                       max_gain, min_gain))

    ctx.schedule_message(1, collect)
    return U.DEFERRED


def _apply(song, accumulator, target, max_gain, min_gain):
    target_level = U.clamp(target, 0.05, 1.0)
    means = {}
    for index, values in accumulator.items():
        if not values:
            continue
        means[index] = sum(values) / float(len(values))
    if not means:
        return {"changed": 0, "reason": "no meter data - start the transport"}
    peak = max(means.values())
    if peak <= 0.0001:
        return {"changed": 0, "reason": "silence"}

    changed = []
    for index, mean in means.items():
        if mean <= 0.0001:
            continue
        track = song.tracks[index]
        gain = (target_level * peak) / mean
        gain = U.clamp(gain, min_gain, max_gain)
        before = track.mixer_device.volume.value
        after = U.clamp(before * gain, 0.0, 1.0)
        if abs(after - before) < 0.0005:
            continue
        track.mixer_device.volume.value = after
        changed.append({
            "index": index,
            "name": track.name,
            "before": round(before, 6),
            "after": round(after, 6),
            "mean_meter": round(mean, 6),
        })
    return {"changed": len(changed), "tracks": changed}


def _gain_stage(ctx, track=0, **kw):
    song = ctx.song_ref
    target = U.track_at(song, track)
    chain = []
    for index, unit in enumerate(target.devices):
        chain.append({"index": index, "name": unit.name, "class": unit.class_name})
    return {"track": target.name, "chain": chain,
            "volume": target.mixer_device.volume.value}


HANDLERS = {
    "mix_report": _report,
    "mix_balance": _balance,
    "mix_chain": _gain_stage,
}
