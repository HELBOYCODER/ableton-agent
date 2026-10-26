# -*- coding: utf-8 -*-
"""OSC transport in front of the same handler table as the TCP/JSON server.

    /hellboy/<method> '{"track": 0, "value": 0.7}'   one JSON object argument
    /hellboy/<method> 0 0.7                          positional arguments

Positional arguments are mapped onto the handler's parameter names, so a
fader on a controller can send /hellboy/track_set_volume 2 0.7 directly.

Replies go to the sender (or to HELLBOY_OSC_REPLY_PORT on the sender's host):

    /hellboy/reply <method> <ok 1|0> <json result or error>

The UDP thread only parses and enqueues. Handlers still run on Live's main
thread through the surface's _tick(). Standard library only.
"""

from __future__ import absolute_import, print_function, unicode_literals

import inspect
import json
import os
import socket
import struct
import threading

PREFIX = "/hellboy/"
DEFAULT_PORT = 8972
MAX_DATAGRAM = 65000

# Built-in methods take a params dict, so their positional names live here.
BUILTIN_ARGS = {
    "session_set_tempo": ("tempo",),
    "session_set_signature": ("numerator", "denominator"),
    "session_set_master_volume": ("value",),
    "transport_seek": ("time",),
    "transport_set_loop": ("enabled", "start", "length"),
}


# ------------------------------------------------------------------ decoding
def _read_string(data, offset):
    end = data.index(b"\0", offset)
    text = data[offset:end].decode("utf-8", "replace")
    return text, (end + 4) & ~3


def _read_blob(data, offset):
    size = struct.unpack(">i", data[offset:offset + 4])[0]
    start = offset + 4
    return data[start:start + size], (start + size + 3) & ~3


def parse_message(data):
    """Decode one OSC message -> (address, [args]). Raises ValueError."""
    try:
        address, offset = _read_string(data, 0)
        if offset >= len(data):
            return address, []
        tags, offset = _read_string(data, offset)
    except (ValueError, IndexError):
        raise ValueError("malformed OSC message")
    if not tags.startswith(","):
        return address, []
    args = []
    for tag in tags[1:]:
        if tag == "i":
            args.append(struct.unpack(">i", data[offset:offset + 4])[0])
            offset += 4
        elif tag == "f":
            args.append(round(struct.unpack(">f", data[offset:offset + 4])[0], 6))
            offset += 4
        elif tag == "d":
            args.append(struct.unpack(">d", data[offset:offset + 8])[0])
            offset += 8
        elif tag == "h":
            args.append(struct.unpack(">q", data[offset:offset + 8])[0])
            offset += 8
        elif tag in ("s", "S"):
            value, offset = _read_string(data, offset)
            args.append(value)
        elif tag == "b":
            value, offset = _read_blob(data, offset)
            args.append(value.decode("utf-8", "replace"))
        elif tag == "T":
            args.append(True)
        elif tag == "F":
            args.append(False)
        elif tag in ("N", "I"):
            args.append(None)
        else:
            raise ValueError("unsupported OSC type tag %r" % tag)
    return address, args


def parse_packet(data):
    """Decode a message or a (nested) bundle -> list of (address, args)."""
    if data.startswith(b"#bundle\0"):
        messages = []
        offset = 16  # "#bundle\0" + 8 byte time tag
        while offset + 4 <= len(data):
            size = struct.unpack(">i", data[offset:offset + 4])[0]
            offset += 4
            messages.extend(parse_packet(data[offset:offset + size]))
            offset += size
        return messages
    return [parse_message(data)]


# ------------------------------------------------------------------ encoding
def _pad(raw):
    raw += b"\0"
    return raw + b"\0" * ((4 - len(raw) % 4) % 4)


def encode_message(address, args):
    tags = ","
    payload = b""
    for value in args:
        if isinstance(value, bool):
            tags += "T" if value else "F"
        elif isinstance(value, int):
            tags += "i"
            payload += struct.pack(">i", value)
        elif isinstance(value, float):
            tags += "f"
            payload += struct.pack(">f", value)
        else:
            tags += "s"
            payload += _pad(str(value).encode("utf-8"))
    return _pad(address.encode("utf-8")) + _pad(tags.encode("utf-8")) + payload


# ------------------------------------------------------------------ requests
def positional_names(surface, method):
    if method in BUILTIN_ARGS:
        return BUILTIN_ARGS[method]
    handler = surface._handlers.get(method)
    if handler is None:
        return ()
    try:
        params = list(inspect.signature(handler).parameters.values())[1:]  # drop ctx
    except (TypeError, ValueError):
        return ()
    return tuple(p.name for p in params
                 if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY))


def to_request(surface, address, args):
    if not address.startswith(PREFIX):
        raise ValueError("address must start with %s" % PREFIX)
    method = address[len(PREFIX):].strip("/").replace("/", "_")
    if len(args) == 1 and isinstance(args[0], str) and args[0].lstrip().startswith("{"):
        params = json.loads(args[0])
    else:
        names = positional_names(surface, method)
        if len(args) > len(names):
            raise ValueError("%s takes at most %d positional arguments (%s)"
                             % (method, len(names), ", ".join(names)))
        params = dict(zip(names, args))
    return {"id": 0, "method": method, "params": params}


class OscReplyTarget(object):
    """Quacks like a socket for the surface's _send(): converts the JSON reply
    line into an OSC /hellboy/reply message."""

    def __init__(self, sock, address, method):
        self._sock = sock
        self._address = address
        self._method = method

    def sendall(self, line):
        try:
            payload = json.loads(line.decode("utf-8"))
        except ValueError:
            return
        ok = 1 if payload.get("ok") else 0
        body = json.dumps(payload.get("result") if ok else payload.get("error"))
        packet = encode_message("/hellboy/reply", [self._method, ok, body])
        if len(packet) > MAX_DATAGRAM:
            packet = encode_message("/hellboy/reply", [
                self._method, ok, json.dumps({"truncated": True,
                                              "note": "reply too large for UDP; use the TCP port"})])
        try:
            self._sock.sendto(packet, self._address)
        except (OSError, socket.error):
            pass


class OscServer(object):
    def __init__(self, surface, host, port, reply_port=None):
        self._surface = surface
        self._reply_port = reply_port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        # see the TCP accept loop: a timeout is what lets close() take effect
        self._sock.settimeout(0.25)
        self._closing = False
        self.port = self._sock.getsockname()[1]
        self.host = host
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()

    def _loop(self):
        while not self._closing:
            try:
                data, sender = self._sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except (OSError, socket.error):
                break
            reply_to = (sender[0], self._reply_port) if self._reply_port else sender
            try:
                messages = parse_packet(data)
            except Exception:
                continue
            for address, args in messages:
                method = address[len(PREFIX):] if address.startswith(PREFIX) else address
                target = OscReplyTarget(self._sock, reply_to, method)
                try:
                    request = to_request(self._surface, address, args)
                except Exception as error:
                    target.sendall(json.dumps({"ok": False, "error": "%s: %s" % (
                        type(error).__name__, error)}).encode("utf-8"))
                    continue
                self._surface._enqueue(target, request)

    def close(self):
        """Stop and wait until the port is really released (at most one poll)."""
        self._closing = True
        self._thread.join(1.0)
        try:
            self._sock.close()
        except (OSError, socket.error):
            pass


def start(surface):
    """Start the OSC server from the environment, or return None if disabled."""
    try:
        port = int(os.environ.get("HELLBOY_OSC_PORT", DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    if port < 0 or os.environ.get("HELLBOY_OSC_PORT", "") == "0":
        return None
    host = os.environ.get("HELLBOY_OSC_HOST", "127.0.0.1")
    reply_port = os.environ.get("HELLBOY_OSC_REPLY_PORT")
    try:
        return OscServer(surface, host, port, int(reply_port) if reply_port else None)
    except (OSError, socket.error, ValueError) as error:
        surface.log_message("Hellboy Prod OSC disabled: %s" % error)
        return None
