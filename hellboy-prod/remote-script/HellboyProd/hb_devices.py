# -*- coding: utf-8 -*-
"""Device inspection, parameter control and loading from the browser."""

from __future__ import absolute_import, print_function, unicode_literals

from . import hb_util as U


def _list(ctx, track=0, **kw):
    target = U.track_at(ctx.song_ref, track)
    return {"devices": [U.device_brief(i, d) for i, d in enumerate(target.devices)]}


def _params(ctx, track=0, device=0, **kw):
    target = U.track_at(ctx.song_ref, track)
    unit = U.device_at(target, device)
    return {"device": unit.name,
            "parameters": [U.parameter_brief(i, p)
                           for i, p in enumerate(unit.parameters)]}


def _get_param(ctx, track=0, device=0, index=None, name=None, **kw):
    target = U.track_at(ctx.song_ref, track)
    unit = U.device_at(target, device)
    param = U.parameter_at(unit, index, name)
    return {"name": param.name, "value": param.value,
            "display": getattr(param, "display_value", None)}


def _set_param(ctx, track=0, device=0, index=None, name=None,
               value=0.0, normalized=False, **kw):
    target = U.track_at(ctx.song_ref, track)
    unit = U.device_at(target, device)
    param = U.parameter_at(unit, index, name)
    if U.as_bool(normalized, False):
        param.value = param.min + U.norm(value) * (param.max - param.min)
    else:
        target_value = U.as_float(value, param.value)
        param.value = max(param.min, min(param.max, target_value))
    return {"name": param.name, "value": param.value,
            "display": getattr(param, "display_value", None)}


def _set_active(ctx, track=0, device=0, active=True, **kw):
    target = U.track_at(ctx.song_ref, track)
    unit = U.device_at(target, device)
    unit.is_active = U.as_bool(active, True)
    return {"name": unit.name, "active": bool(unit.is_active)}


def _delete(ctx, track=0, device=0, **kw):
    song = ctx.song_ref
    target = U.track_at(song, track)
    position = list(target.devices).index(U.device_at(target, device))
    target.delete_device(position)
    return {"deleted": position}


def _move(ctx, track=0, device=0, to=0, **kw):
    song = ctx.song_ref
    target = U.track_at(song, track)
    unit = U.device_at(target, device)
    mover = getattr(song, "move_device", None)
    if not callable(mover):
        return {"ok": False, "reason": "move_device not exposed by this Live version"}
    mover(unit, target, U.as_int(to, 0))
    return {"ok": True, "moved_to": U.as_int(to, 0)}


def _chains(ctx, track=0, device=0, **kw):
    target = U.track_at(ctx.song_ref, track)
    unit = U.device_at(target, device)
    if not getattr(unit, "can_have_chains", False):
        return {"chains": []}
    return {"chains": [{"index": i, "name": c.name,
                        "device_count": len(c.devices)}
                       for i, c in enumerate(unit.chains)]}


def _chain_devices(ctx, track=0, device=0, chain=0, **kw):
    target = U.track_at(ctx.song_ref, track)
    unit = U.device_at(target, device)
    if not getattr(unit, "can_have_chains", False):
        raise ValueError("device has no chains")
    selected = unit.chains[U.as_int(chain, 0)]
    return {"devices": [U.device_brief(i, d) for i, d in enumerate(selected.devices)]}


def _add(ctx, track=0, path="", index=-1, **kw):
    from . import hb_browser

    song = ctx.song_ref
    target = U.track_at(song, track)
    song.view.selected_track = target
    item = hb_browser.resolve(ctx, path)
    if not getattr(item, "is_loadable", False):
        raise ValueError("browser item is not loadable: %s" % path)
    song.view.selected_track = target
    count_before = len(target.devices)
    song.view.selected_track = target
    browser = hb_browser.browser(ctx)
    browser.load_item(item)
    return {"requested": path, "device_count_before": count_before,
            "device_count_after": len(target.devices)}


HANDLERS = {
    "device_list": _list,
    "device_params": _params,
    "device_get_param": _get_param,
    "device_set_param": _set_param,
    "device_set_active": _set_active,
    "device_delete": _delete,
    "device_move": _move,
    "device_chains": _chains,
    "device_chain_devices": _chain_devices,
    "device_add": _add,
}
