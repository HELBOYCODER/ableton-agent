# -*- coding: utf-8 -*-
"""Automation envelopes on session clips."""

from __future__ import absolute_import, print_function, unicode_literals

from . import hb_util as U


def _parameter(ctx, track, slot, device, param):
    clip = U.clip_at(ctx.song_ref, track, slot)
    target_track = U.track_at(ctx.song_ref, track)
    unit = U.device_at(target_track, device)
    parameter = U.parameter_at(unit, param)
    return clip, parameter


def _envelope(ctx, track, slot, device, param, create=False):
    clip, parameter = _parameter(ctx, track, slot, device, param)
    envelope = clip.automation_envelope(parameter)
    if envelope is None and create:
        envelope = clip.create_automation_envelope(parameter)
    return envelope


def _get(ctx, track=0, slot=0, device=0, param=0, grid=0.25, **kw):
    envelope = _envelope(ctx, track, slot, device, param, create=False)
    if envelope is None:
        return {"exists": False, "points": []}
    clip, parameter = _parameter(ctx, track, slot, device, param)
    points = []
    events = getattr(envelope, "events", None)
    if events is not None:
        try:
            for event in events:
                points.append({"time": event[0] if isinstance(event, (list, tuple)) else event.time,
                               "value": event[1] if isinstance(event, (list, tuple)) else event.value})
            return {"exists": True, "points": points, "parameter": parameter.name}
        except Exception:
            points = []
    step = max(0.001, U.as_float(grid, 0.25))
    time = 0.0
    length = float(clip.length)
    while time <= length + 1e-6:
        points.append({"time": round(time, 6),
                       "value": round(float(envelope.value_at_time(time)), 6)})
        time += step
    return {"exists": True, "points": points, "parameter": parameter.name}


def _write(ctx, track=0, slot=0, device=0, param=0, points=None, clear=True, **kw):
    clip, parameter = _parameter(ctx, track, slot, device, param)
    envelope = clip.automation_envelope(parameter)
    if envelope is None:
        envelope = clip.create_automation_envelope(parameter)
    if envelope is None:
        raise ValueError("could not create automation envelope")
    if clear:
        envelope.clear()
    written = 0
    for point in (points or []):
        envelope.add_event(U.as_float(point.get("time", 0.0), 0.0),
                           U.as_float(point.get("value", 0.0), 0.0))
        written += 1
    return {"written": written, "parameter": parameter.name,
            "value": parameter.value}


def _clear(ctx, track=0, slot=0, device=0, param=0, **kw):
    envelope = _envelope(ctx, track, slot, device, param, create=False)
    if envelope is None:
        return {"cleared": False, "reason": "no envelope"}
    envelope.clear()
    return {"cleared": True}


def _list_envelopes(ctx, track=0, slot=0, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    target_track = U.track_at(ctx.song_ref, track)
    found = []
    for device_index, unit in enumerate(target_track.devices):
        for parameter_index, parameter in enumerate(unit.parameters):
            if clip.automation_envelope(parameter) is not None:
                found.append({"device": device_index,
                              "device_name": unit.name,
                              "parameter": parameter_index,
                              "parameter_name": parameter.name})
    return {"envelopes": found}


def _clear_all(ctx, track=0, slot=0, **kw):
    clip = U.clip_at(ctx.song_ref, track, slot)
    clip.clear_all_envelopes()
    return {"cleared": True}


HANDLERS = {
    "automation_get": _get,
    "automation_write": _write,
    "automation_clear": _clear,
    "automation_list": _list_envelopes,
    "automation_clear_all": _clear_all,
}
