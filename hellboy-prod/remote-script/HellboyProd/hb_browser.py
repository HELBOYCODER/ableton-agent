# -*- coding: utf-8 -*-
"""Read-only access to the Live browser and loading of browser items."""

from __future__ import absolute_import, print_function, unicode_literals

import Live
from . import hb_util as U

ROOT_NAMES = (
    "instruments", "sounds", "drums", "audio_effects", "midi_effects",
    "plugins", "user_library", "user_folders", "packs", "max_for_live",
    "samples", "clips", "current_project",
)

MAX_SEARCH_DEPTH = 6
MAX_SEARCH_NODES = 20000


def browser(ctx):
    return Live.Application.get_application().browser


def _item_brief(item, path):
    return {
        "name": item.name,
        "path": path,
        "folder": bool(getattr(item, "is_folder", False)),
        "loadable": bool(getattr(item, "is_loadable", False)),
        "device": bool(getattr(item, "is_device", False)),
        "uri": getattr(item, "uri", None),
    }


def resolve(ctx, path):
    parts = [p for p in str(path).split("/") if p]
    if not parts:
        raise ValueError("empty browser path")
    root = parts[0]
    if root not in ROOT_NAMES:
        raise ValueError("unknown browser root %r (known: %s)"
                         % (root, ", ".join(ROOT_NAMES)))
    item = getattr(browser(ctx), root, None)
    if item is None:
        raise ValueError("browser root %r is empty in this Live version" % root)
    for part in parts[1:]:
        match = None
        for child in item.children:
            if child.name == part:
                match = child
                break
        if match is None:
            raise ValueError("no child %r under %r" % (part, item.name))
        item = match
    return item


def _roots(ctx, **kw):
    node = browser(ctx)
    roots = []
    for name in ROOT_NAMES:
        item = getattr(node, name, None)
        if item is None:
            continue
        roots.append({"name": name, "children": len(item.children)})
    return {"roots": roots}


def _children(ctx, path="", depth=1, limit=500, **kw):
    node = browser(ctx)
    if not path:
        entries = []
        for name in ROOT_NAMES:
            item = getattr(node, name, None)
            if item is None:
                continue
            entries.append(_item_brief(item, name))
        return {"path": "", "items": entries[:limit]}

    item = resolve(ctx, path)
    results = []
    queue = [(item, path, 0)]
    while queue and len(results) < limit:
        current, current_path, level = queue.pop(0)
        if level >= U.as_int(depth, 1):
            continue
        for child in current.children:
            child_path = "%s/%s" % (current_path, child.name)
            results.append(_item_brief(child, child_path))
            if getattr(child, "is_folder", False):
                queue.append((child, child_path, level + 1))
    return {"path": path, "items": results[:limit]}


def _search(ctx, query="", limit=25, categories=None, loadable_only=True, **kw):
    needle = str(query).lower().strip()
    if not needle:
        raise ValueError("empty search query")
    node = browser(ctx)
    wanted = [c for c in (categories or ROOT_NAMES) if c in ROOT_NAMES]
    limit = max(1, min(200, U.as_int(limit, 25)))
    results = []
    visited = 0

    for root_name in wanted:
        root = getattr(node, root_name, None)
        if root is None:
            continue
        queue = [(root, root_name, 0)]
        while queue and len(results) < limit and visited < MAX_SEARCH_NODES:
            current, current_path, level = queue.pop(0)
            visited += 1
            if level >= MAX_SEARCH_DEPTH:
                continue
            for child in current.children:
                child_path = "%s/%s" % (current_path, child.name)
                is_loadable = bool(getattr(child, "is_loadable", False))
                is_folder = bool(getattr(child, "is_folder", False))
                if needle in child.name.lower() and (is_loadable or not loadable_only):
                    results.append(_item_brief(child, child_path))
                    if len(results) >= limit:
                        break
                if is_folder:
                    queue.append((child, child_path, level + 1))
    return {"query": query, "count": len(results), "items": results}


def _item_info(ctx, path="", **kw):
    return _item_brief(resolve(ctx, path), path)


def _load(ctx, path="", track=None, **kw):
    song = ctx.song_ref
    item = resolve(ctx, path)
    if not getattr(item, "is_loadable", False):
        raise ValueError("browser item is not loadable: %s" % path)
    if track is not None:
        song.view.selected_track = U.track_at(song, track)
    node = browser(ctx)
    node.load_item(item)
    return {"loaded": path, "into_track": track}


HANDLERS = {
    "browser_roots": _roots,
    "browser_children": _children,
    "browser_search": _search,
    "browser_item": _item_info,
    "browser_load": _load,
}
