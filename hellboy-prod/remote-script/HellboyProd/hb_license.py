# -*- coding: utf-8 -*-
"""Optional offline-tolerant license check against a remote activation API."""

from __future__ import absolute_import, print_function, unicode_literals

import json
import os
import threading

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    _HAS_URLLIB = True
except ImportError:  # pragma: no cover
    _HAS_URLLIB = False

VALIDATE_URL = "https://api.lemonsqueezy.com/v1/licenses/validate"

_STATE = {
    "checked": False,
    "valid": None,
    "detail": "not checked",
    "license_prefix": None,
    "activation_limit": None,
    "activation_usage": None,
}


def _apply(payload):
    meta = payload.get("meta") or {}
    _STATE["checked"] = True
    _STATE["valid"] = bool(payload.get("valid"))
    _STATE["detail"] = payload.get("error") or meta.get("store_name") or "checked"
    _STATE["activation_limit"] = meta.get("activation_limit")
    _STATE["activation_usage"] = meta.get("activation_usage")


def _check(ctx, license_key=None, **kw):
    key = license_key or os.environ.get("HELLBOY_LICENSE", "")
    if not key:
        return {"started": False, "detail": "no license key provided"}
    if not _HAS_URLLIB:
        return {"started": False, "detail": "urllib unavailable"}

    _STATE["license_prefix"] = key[:8] + "..."
    _STATE["detail"] = "checking"

    def work():
        try:
            body = urlencode({"license_key": key}).encode("utf-8")
            request = Request(VALIDATE_URL, data=body, method="POST")
            request.add_header("Accept", "application/json")
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urlopen(request, timeout=8) as response:
                _apply(json.loads(response.read().decode("utf-8")))
        except Exception as exc:
            _STATE["checked"] = True
            _STATE["valid"] = None
            _STATE["detail"] = "offline: %s" % type(exc).__name__

    thread = threading.Thread(target=work)
    thread.daemon = True
    thread.start()
    return {"started": True}


def _status(ctx, **kw):
    return dict(_STATE)


HANDLERS = {
    "license_check": _check,
    "license_status": _status,
}
