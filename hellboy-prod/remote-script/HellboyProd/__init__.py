# -*- coding: utf-8 -*-
"""Hellboy Prod - Ableton Live remote script.

A terminal coding agent drives a live session through this control surface:

    agent --stdio(MCP)--> hellboy-bridge --TCP/JSON--> THIS SCRIPT --> Live

Threading contract (do not break):
  * The socket threads ONLY append (conn, request) to a queue.
  * All Live Object Model access happens on the MAIN thread, inside _tick(),
    which is re-armed every tick through self.schedule_message(1, self._tick).
  * Every handler is wrapped in try/except; a handler bug returns an error
    object, it never kills the socket or the surface.

Handlers live in hb_*.py modules, each exposing a HANDLERS dict that is merged
here. Built-in session/transport methods are defined on the class itself.
"""

from __future__ import absolute_import, print_function, unicode_literals

import json
import os
import re
import socket
import threading
import traceback

from _Framework.ControlSurface import ControlSurface

from . import hb_util as U
from . import hb_tracks
from . import hb_clips
from . import hb_notes
from . import hb_devices
from . import hb_browser
from . import hb_automation
from . import hb_mix
from . import hb_quickloop
from . import hb_license
from . import hb_arrangement
from . import hb_osc

PRODUCT = "Hellboy Prod"
SCRIPT_VERSION = "1.3.0"
API_VERSION = 1
HOST = "127.0.0.1"
DEFAULT_PORT = 8971
POLL_SECONDS = 0.25

# Methods that must not be wrapped in an undo step of their own.
NO_UNDO_GROUP = frozenset(("session_undo", "session_redo", "hello", "ping", "shutdown"))

# Read-only methods never open an undo step: UIs poll them constantly and they
# must not leave empty entries in Live's undo history.
READ_ONLY = re.compile(
    r"(_state|_overview|_list|_brief|_info|_get|_get_param|_params|_stats|_status"
    r"|_report|^arrangement_clips|_chains|_chain_devices|_detect_key|_roots|_children|_search"
    r"|_item|^mix_chain)$")

MODULES = (
    hb_tracks, hb_clips, hb_notes, hb_devices, hb_browser,
    hb_automation, hb_mix, hb_quickloop, hb_license, hb_arrangement,
)


def create_instance(c_instance):
    return HellboyProd(c_instance)


class HellboyProd(ControlSurface):
    def __init__(self, c_instance):
        super(HellboyProd, self).__init__(c_instance)
        self._queue = []
        self._lock = threading.Lock()
        self._deferred_targets = []
        self._server = None
        self._clients = set()
        self._closing = False
        self._port = self._desired_port()

        self._handlers = {}
        for module in MODULES:
            self._handlers.update(getattr(module, "HANDLERS", {}))
        self._builtins = self._build_builtins()
        self._method_names = sorted(set(list(self._handlers.keys()) + list(self._builtins.keys())))

        self._osc = None
        with self.component_guard():
            self._start_server()
            self._osc = hb_osc.start(self)
        self.schedule_message(1, self._tick)
        self.log_message("%s bridge listening on %s:%s" % (PRODUCT, HOST, self._port))
        if self._osc is not None:
            self.log_message("%s OSC listening on %s:%s" % (PRODUCT, self._osc.host, self._osc.port))

    # ------------------------------------------------------------------ ctx API
    @property
    def song_ref(self):
        return self.song()

    def reply_later(self, producer):
        """Called by a deferred handler once its result is ready."""
        target = None
        if self._deferred_targets:
            target = self._deferred_targets.pop(0)

        def deliver():
            try:
                result = producer()
                payload = {"id": target[0] if target else None, "ok": True, "result": result}
            except Exception as error:
                payload = {"id": target[0] if target else None, "ok": False,
                           "error": "%s: %s" % (type(error).__name__, error),
                           "trace": traceback.format_exc()}
            if target:
                self._send(target[1], payload)

        self.schedule_message(1, deliver)

    # --------------------------------------------------------------- networking
    def _desired_port(self):
        try:
            return int(os.environ.get("HELLBOY_PORT", DEFAULT_PORT))
        except (TypeError, ValueError):
            return DEFAULT_PORT

    def _start_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((HOST, self._port))
        except OSError:
            server.bind((HOST, 0))  # port taken -> ephemeral, reported in hello
        self._port = server.getsockname()[1]
        server.listen(8)
        # A timeout lets the loop notice disconnect(): on Linux, close() from
        # another thread does not wake a blocked accept(), so the port would
        # stay bound and a reloaded surface would land on a random port.
        server.settimeout(POLL_SECONDS)
        self._server = server

        def accept_loop():
            while not self._closing:
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                conn.setblocking(True)
                with self._lock:
                    self._clients.add(conn)
                threading.Thread(target=self._read_loop, args=(conn,), daemon=True).start()
            try:
                server.close()
            except OSError:
                pass

        self._accept_thread = threading.Thread(target=accept_loop, daemon=True)
        self._accept_thread.start()

    def _read_loop(self, conn):
        buffer = b""
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        request = json.loads(line.decode("utf-8"))
                    except ValueError:
                        continue
                    self._enqueue(conn, request)
        except OSError:
            pass
        finally:
            with self._lock:
                self._clients.discard(conn)
            try:
                conn.close()
            except OSError:
                pass

    def _enqueue(self, target, request):
        """The only thing transport threads may do: hand work to the main thread."""
        with self._lock:
            self._queue.append((target, request))

    def _send(self, conn, payload):
        try:
            conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError:
            pass

    # ------------------------------------------------------------- main thread
    def _tick(self):
        if self._closing:
            return
        while True:
            with self._lock:
                if not self._queue:
                    break
                conn, request = self._queue.pop(0)
            self._handle(conn, request)
        self.schedule_message(1, self._tick)

    def _handle(self, conn, request):
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        try:
            result = self._dispatch(method, params)
            if result is U.DEFERRED:
                self._deferred_targets.append((request_id, conn))
                return
            self._send(conn, {"id": request_id, "ok": True, "result": result})
        except Exception as error:
            self._send(conn, {
                "id": request_id,
                "ok": False,
                "error": "%s: %s" % (type(error).__name__, error),
                "trace": traceback.format_exc(),
            })

    def _dispatch(self, method, params):
        if method in self._builtins:
            call = lambda: self._builtins[method](params)
        else:
            handler = self._handlers.get(method)
            if handler is None:
                raise NameError("UnknownMethod: %s" % method)
            call = lambda: handler(self, **params)
        # One agent call = one undo step in Live (Live 11+ exposes the markers).
        song = self.song()
        grouped = (method not in NO_UNDO_GROUP and not READ_ONLY.search(method)
                   and hasattr(song, "begin_undo_step"))
        if grouped:
            song.begin_undo_step()
        try:
            return call()
        finally:
            if grouped:
                song.end_undo_step()

    # ----------------------------------------------------------------- builtins
    def _build_builtins(self):
        return {
            "hello": self._m_hello,
            "ping": self._m_ping,
            "shutdown": self._m_shutdown,
            "session_state": self._m_session_state,
            "session_overview": self._m_session_overview,
            "session_set_tempo": self._m_session_set_tempo,
            "session_set_signature": self._m_session_set_signature,
            "session_save": self._m_session_save,
            "session_undo": self._m_session_undo,
            "session_redo": self._m_session_redo,
            "session_capture_scene": self._m_session_capture_scene,
            "session_set_master_volume": self._m_session_set_master_volume,
            "transport_play": self._m_transport_play,
            "transport_stop": self._m_transport_stop,
            "transport_seek": self._m_transport_seek,
            "transport_set_loop": self._m_transport_set_loop,
            "transport_stop_all_clips": self._m_transport_stop_all_clips,
        }

    def _m_hello(self, params):
        return {
            "product": PRODUCT,
            "api": API_VERSION,
            "version": SCRIPT_VERSION,
            "port": self._port,
            "osc_port": self._osc.port if self._osc is not None else None,
            "live_version": self._live_version(),
            "methods": self._method_names,
        }

    def _m_ping(self, params):
        return {"pong": True}

    def _m_shutdown(self, params):
        return {"ok": True, "note": "remote script stays loaded; close Live to stop it"}

    def _live_version(self):
        try:
            import Live
            app = Live.Application.get_application()
            return "%s.%s.%s" % (app.get_major_version(), app.get_minor_version(),
                                 app.get_bugfix_version())
        except Exception:
            return None

    def _m_session_state(self, params):
        song = self.song()
        tracks = [U.track_brief(song, i, t) for i, t in enumerate(song.tracks)]
        returns = [{"index": i, "name": t.name} for i, t in enumerate(song.return_tracks)]
        scenes = [{"index": i, "name": s.name} for i, s in enumerate(song.scenes)]
        selected = None
        try:
            selected = U.track_position(song, song.view.selected_track)
        except Exception:
            selected = None
        return {
            "product": PRODUCT,
            "tempo": round(song.tempo, 6),
            "signature": [song.signature_numerator, song.signature_denominator],
            "playing": bool(song.is_playing),
            "track_count": len(song.tracks),
            "return_count": len(song.return_tracks),
            "scene_count": len(song.scenes),
            "selected_track": selected,
            "tracks": tracks,
            "returns": returns,
            "scenes": scenes,
            "master_volume": round(song.master_track.mixer_device.volume.value, 6),
        }

    def _m_session_overview(self, params):
        song = self.song()
        lines = ["%s @ %.2f BPM, %d/%d, %d tracks" % (
            PRODUCT, song.tempo, song.signature_numerator,
            song.signature_denominator, len(song.tracks))]
        for index, track in enumerate(song.tracks):
            kind = "midi" if getattr(track, "has_midi_input", False) else "audio"
            clips = sum(1 for slot in track.clip_slots if slot.has_clip)
            lines.append("  %2d %-20s %-5s %d clips %d devices" % (
                index, track.name[:20], kind, clips, len(track.devices)))
        return {"text": "\n".join(lines), "track_count": len(song.tracks)}

    def _m_session_set_tempo(self, params):
        song = self.song()
        song.tempo = U.clamp(params.get("tempo", song.tempo), 20.0, 999.0)
        return {"tempo": round(song.tempo, 6)}

    def _m_session_set_signature(self, params):
        song = self.song()
        if params.get("numerator") is not None:
            song.signature_numerator = U.as_int(params.get("numerator"), song.signature_numerator)
        if params.get("denominator") is not None:
            song.signature_denominator = U.as_int(params.get("denominator"), song.signature_denominator)
        return {"signature": [song.signature_numerator, song.signature_denominator]}

    def _m_session_save(self, params):
        song = self.song()
        saver = getattr(song, "save", None)
        if callable(saver):
            saver()
            return {"saved": True}
        return {"saved": False, "reason": "save not exposed by this Live version"}

    def _m_session_undo(self, params):
        self.song().undo()
        return {"ok": True}

    def _m_session_redo(self, params):
        self.song().redo()
        return {"ok": True}

    def _m_session_capture_scene(self, params):
        song = self.song()
        capture = getattr(song, "capture_and_insert_scene", None)
        if callable(capture):
            capture()
            return {"ok": True, "scene_count": len(song.scenes)}
        return {"ok": False, "reason": "capture_and_insert_scene not available"}

    def _m_session_set_master_volume(self, params):
        song = self.song()
        song.master_track.mixer_device.volume.value = U.norm(params.get("value", 0.85))
        return {"master_volume": round(song.master_track.mixer_device.volume.value, 6)}

    def _m_transport_play(self, params):
        self.song().start_playing()
        return {"playing": True}

    def _m_transport_stop(self, params):
        self.song().stop_playing()
        return {"playing": False}

    def _m_transport_seek(self, params):
        song = self.song()
        song.current_song_time = max(0.0, U.as_float(params.get("time", 0.0), 0.0))
        return {"time": round(song.current_song_time, 6)}

    def _m_transport_set_loop(self, params):
        song = self.song()
        if params.get("enabled") is not None:
            song.loop = U.as_bool(params.get("enabled"), True)
        if params.get("start") is not None:
            song.loop_start = max(0.0, U.as_float(params.get("start"), 0.0))
        if params.get("length") is not None:
            song.loop_length = max(0.0, U.as_float(params.get("length"), song.loop_length))
        return {"loop": bool(song.loop), "start": song.loop_start, "length": song.loop_length}

    def _m_transport_stop_all_clips(self, params):
        self.song().stop_all_clips()
        return {"stopped": True}

    # --------------------------------------------------------------- teardown
    def disconnect(self):
        self._closing = True
        if self._server is not None:
            # wait for the accept loop to close the socket so the port is free
            # for the next instance Live creates right after this call
            self._accept_thread.join(1.0)
        # drop clients so the bridge sees the close and reconnects to the
        # next instance of the surface
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for conn in clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        if self._osc is not None:
            self._osc.close()
        super(HellboyProd, self).disconnect()
