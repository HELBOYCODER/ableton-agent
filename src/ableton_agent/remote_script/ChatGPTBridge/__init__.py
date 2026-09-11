# -*- coding: utf-8 -*-
"""
ChatGPTBridge - Ableton Live MIDI Remote Script
================================================
A Control Surface that listens for JSON commands over UDP (127.0.0.1:9000)
and executes them against the Live Object Model (LOM).

Commands are produced by the ableton-agent CLI. Each command:
    {"action": "<name>", "args": {...}, "id": <optional>}

Every command is answered with a UDP reply:
    {"status": "ok", "action": ..., "result": ..., "id": ...}
    {"status": "error", "action": ..., "error": "...", "id": ...}

Place this folder (ChatGPTBridge/) inside Ableton's MIDI Remote Scripts
directory, then select "ChatGPTBridge" as a Control Surface in
Preferences > Link/Tempo/MIDI.
"""

from __future__ import absolute_import, print_function

import collections
import json
import socket
import threading
import os

from _Framework.ControlSurface import ControlSurface

try:
    import Live
except ImportError:  # pragma: no cover - only available inside Live
    Live = None

BRIDGE_VERSION = "0.4.0"

HOST = os.environ.get("ABLETON_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ABLETON_BRIDGE_PORT", "9000"))

# Live's mixer volume parameter is normalised 0.0 - 1.0 where 0.85 == 0 dB.
UNITY_VOLUME = 0.85

# Optional: root folders of your sample library (configurable via ABLETON_SAMPLE_ROOTS)
SAMPLE_ROOTS = [
    os.path.expanduser("~/Samples"),
    os.path.expanduser("~/Music/Samples"),
]
_extra_roots = os.environ.get("ABLETON_SAMPLE_ROOTS") or os.environ.get("SAMPLE_ROOTS")
if _extra_roots:
    for r in _extra_roots.split(os.pathsep):
        r_exp = os.path.expanduser(r.strip())
        if r_exp and r_exp not in SAMPLE_ROOTS:
            SAMPLE_ROOTS.append(r_exp)


def _find_sample(filename):
    """Search the sample roots (recursively, depth-limited) for a file name."""
    filename = filename.replace("\\", "/")
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename
    base = os.path.basename(filename).lower()
    stem = os.path.splitext(base)[0]
    fuzzy = None
    for root in SAMPLE_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth > 4:
                continue
            for f in filenames:
                low = f.lower()
                if low == base:
                    return os.path.join(dirpath, f)
                if fuzzy is None and stem and stem in low:
                    fuzzy = os.path.join(dirpath, f)
    return fuzzy


class ChatGPTBridge(ControlSurface):

    def __init__(self, c_instance):
        super(ChatGPTBridge, self).__init__(c_instance)
        self._stop = False
        self._sock = None
        self._queue = collections.deque()
        self._queue_lock = threading.Lock()
        # Index of the most recently created track; lets plans address the
        # track they just made with track_index = -1 instead of guessing.
        self._last_track_index = None
        with self.component_guard():
            pass
        self._thread = threading.Thread(target=self._listen)
        self._thread.daemon = True
        self._thread.start()
        self.log_message("ChatGPTBridge v%s: listening on udp://%s:%d" % (BRIDGE_VERSION, HOST, PORT))
        self.show_message("ChatGPTBridge connected - send commands to UDP port %d" % PORT)

    def disconnect(self):
        self._stop = True
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        super(ChatGPTBridge, self).disconnect()

    # ------------------------------------------------------------------
    # UDP listener thread -> queue -> Live's main thread
    # ------------------------------------------------------------------
    def _listen(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, PORT))
            s.settimeout(1.0)
        except Exception as e:
            self.log_message("ChatGPTBridge: cannot bind udp://%s:%d (%s)" % (HOST, PORT, e))
            return
        self._sock = s
        while not self._stop:
            try:
                data, addr = s.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception:
                break
            try:
                cmd = json.loads(data.decode("utf-8"))
            except Exception as e:
                self.log_message("ChatGPTBridge: bad packet: %s" % e)
                continue
            with self._queue_lock:
                self._queue.append((cmd, addr))

    def update_display(self):
        """Called by Live on the main thread (~every 100ms): drain the queue.

        Commands must touch the LOM from Live's own thread, so the UDP thread
        only enqueues them here.
        """
        super(ChatGPTBridge, self).update_display()
        while True:
            with self._queue_lock:
                if not self._queue:
                    return
                cmd, addr = self._queue.popleft()
            self._execute(cmd, addr)

    # ------------------------------------------------------------------
    # Command dispatcher (runs on Live's main thread)
    # ------------------------------------------------------------------
    def _reply(self, addr, payload):
        if not addr or not self._sock:
            return
        try:
            self._sock.sendto(json.dumps(payload).encode("utf-8"), addr)
        except Exception as e:
            self.log_message("ChatGPTBridge: reply failed: %s" % e)

    def _execute(self, cmd, addr=None):
        song = self.song()
        action = cmd.get("action")
        args = cmd.get("args", {}) or {}
        cmd_id = cmd.get("id")
        handler = getattr(self, "_do_" + str(action), None)
        if handler is None:
            self.log_message("ChatGPTBridge: unknown action %s" % action)
            self._reply(addr, {"status": "error", "action": action, "id": cmd_id,
                               "error": "unknown action: %s" % action})
            return
        try:
            result = handler(song, args)
        except Exception as e:
            self.log_message("ChatGPTBridge: ERROR %s -> %s" % (action, e))
            self._reply(addr, {"status": "error", "action": action, "id": cmd_id,
                               "error": "%s: %s" % (type(e).__name__, e)})
            return
        self.log_message("ChatGPTBridge: OK %s %s" % (action, args))
        payload = {"status": "ok", "action": action, "id": cmd_id}
        if result is not None:
            payload["result"] = result
        self._reply(addr, payload)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    def _track(self, song, ref):
        """Resolve a track by index, by name, or -1 = last created track."""
        tracks = song.tracks
        if isinstance(ref, str) and not ref.lstrip("-").isdigit():
            needle = ref.strip().lower()
            for t in tracks:
                if t.name.lower() == needle:
                    return t
            for t in tracks:
                if needle in t.name.lower():
                    return t
            raise ValueError("no track named %r (have: %s)"
                             % (ref, ", ".join(t.name for t in tracks)))
        idx = int(ref)
        if idx < 0:
            if self._last_track_index is not None and self._last_track_index < len(tracks):
                return tracks[self._last_track_index]
            idx = len(tracks) + idx
        if idx < 0 or idx >= len(tracks):
            raise ValueError("track_index %s out of range (%d tracks)" % (ref, len(tracks)))
        return tracks[idx]

    def _track_ref(self, args):
        for key in ("track_index", "track", "track_name"):
            if key in args and args[key] is not None:
                return args[key]
        return -1

    def _target_track(self, song, args):
        return self._track(song, self._track_ref(args))

    def _clip_slot(self, track, args):
        slot_index = int(args.get("slot", args.get("slot_index", 0)))
        slots = track.clip_slots
        if slot_index < 0 or slot_index >= len(slots):
            raise ValueError("slot %d out of range (%d slots on '%s')"
                             % (slot_index, len(slots), track.name))
        return slots[slot_index], slot_index

    # ------------------------------------------------------------------
    # Project / transport
    # ------------------------------------------------------------------
    def _do_ping(self, song, args):
        return {"bridge_version": BRIDGE_VERSION, "tempo": song.tempo,
                "tracks": len(song.tracks)}

    def _do_set_tempo(self, song, args):
        bpm = float(args.get("bpm", 124.0))
        song.tempo = max(20.0, min(999.0, bpm))
        return {"tempo": song.tempo}

    def _do_play(self, song, args):
        song.is_playing = True

    def _do_stop(self, song, args):
        song.is_playing = False

    def _do_rename_project(self, song, args):
        self.show_message("Project: %s" % args.get("name", ""))

    # ------------------------------------------------------------------
    # Tracks
    # ------------------------------------------------------------------
    def _create_track(self, song, args, factory):
        idx = int(args.get("index", -1))
        before = len(song.tracks)
        factory(idx)
        new_index = idx if 0 <= idx <= before else len(song.tracks) - 1
        track = song.tracks[new_index]
        name = args.get("name")
        if name:
            track.name = name
        self._last_track_index = new_index
        return {"track_index": new_index, "name": track.name}

    def _do_create_midi_track(self, song, args):
        return self._create_track(song, args, song.create_midi_track)

    def _do_create_audio_track(self, song, args):
        return self._create_track(song, args, song.create_audio_track)

    def _do_create_return_track(self, song, args):
        song.create_return_track()
        name = args.get("name")
        track = song.return_tracks[len(song.return_tracks) - 1]
        if name:
            track.name = name
        return {"return_index": len(song.return_tracks) - 1, "name": track.name}

    def _do_delete_track(self, song, args):
        track = self._target_track(song, args)
        song.delete_track(list(song.tracks).index(track))
        self._last_track_index = None

    def _do_rename_track(self, song, args):
        track = self._target_track(song, args)
        track.name = args["name"]
        return {"name": track.name}

    # ------------------------------------------------------------------
    # Mixer
    # ------------------------------------------------------------------
    def _do_set_volume(self, song, args):
        track = self._target_track(song, args)
        value = float(args["value"])
        # Convenience: callers may pass dB (e.g. -6.0) instead of 0..1.
        if value < 0.0 or value > 1.0:
            value = UNITY_VOLUME * (10.0 ** (value / 20.0))
        track.mixer_device.volume.value = max(0.0, min(1.0, value))
        return {"volume": track.mixer_device.volume.value}

    def _do_set_pan(self, song, args):
        track = self._target_track(song, args)
        track.mixer_device.panning.value = max(-1.0, min(1.0, float(args["value"])))

    def _do_mute_track(self, song, args):
        self._target_track(song, args).mute = bool(args.get("mute", True))

    def _do_solo_track(self, song, args):
        self._target_track(song, args).solo = bool(args.get("solo", True))

    def _do_arm_track(self, song, args):
        track = self._target_track(song, args)
        if track.can_be_armed:
            track.arm = bool(args.get("arm", True))

    def _do_add_send(self, song, args):
        """Route a track to a return bus. args: track_index, bus_index, amount(0-1)."""
        track = self._target_track(song, args)
        bus = int(args.get("bus_index", 0))
        sends = track.mixer_device.sends
        if bus >= len(sends):
            raise ValueError("no return bus %d (track has %d sends)" % (bus, len(sends)))
        sends[bus].value = max(0.0, min(1.0, float(args.get("amount", 0.3))))

    # ------------------------------------------------------------------
    # Clips & notes (MIDI)
    # ------------------------------------------------------------------
    def _do_create_clip(self, song, args):
        """args: track_index|track, slot, length_beats, replace(bool)"""
        track = self._target_track(song, args)
        slot, slot_index = self._clip_slot(track, args)
        length = max(0.0625, float(args.get("length_beats", 4.0)))
        if slot.has_clip:
            if args.get("replace", True):
                slot.delete_clip()
            else:
                return {"track": track.name, "slot": slot_index, "created": False}
        if not track.has_midi_input:
            raise ValueError("track '%s' is not a MIDI track" % track.name)
        slot.create_clip(length)
        return {"track": track.name, "slot": slot_index, "length_beats": length,
                "created": True}

    @staticmethod
    def _note_tuple(n):
        return (
            max(0, min(127, int(n["pitch"]))),
            max(0.0, float(n.get("start", 0.0))),
            max(0.015625, float(n.get("length", 0.25))),
            max(1, min(127, int(n.get("velocity", 100)))),
            bool(n.get("mute", False)),
        )

    def _do_add_notes(self, song, args):
        """
        args: track_index|track, slot, replace(bool, default False),
              notes: [{"pitch":60,"start":0.0,"length":0.25,"velocity":100}, ...]
        start/length in beats.
        """
        track = self._target_track(song, args)
        slot, slot_index = self._clip_slot(track, args)
        notes = args.get("notes") or []
        if not notes:
            return {"added": 0}
        if not slot.has_clip:
            # Be forgiving: a plan that forgot create_clip still works.
            if not track.has_midi_input:
                raise ValueError("track '%s' is not a MIDI track" % track.name)
            end = max(float(n.get("start", 0.0)) + float(n.get("length", 0.25)) for n in notes)
            slot.create_clip(max(4.0, float(args.get("length_beats", 0.0)), end))
        clip = slot.clip
        tuples = [self._note_tuple(n) for n in notes]

        if args.get("replace", False):
            self._clear_notes(clip)

        added = self._write_notes(clip, tuples)
        return {"track": track.name, "slot": slot_index, "added": added}

    @staticmethod
    def _clear_notes(clip):
        if hasattr(clip, "remove_notes_extended"):
            clip.remove_notes_extended(0, 128, 0.0, clip.length)
        else:
            clip.select_all_notes()
            clip.replace_selected_notes(tuple())

    def _write_notes(self, clip, tuples):
        """Append notes, preserving what is already in the clip.

        Live 11+ exposes add_new_notes; older versions only have set_notes,
        which *replaces* the clip content - so merge manually there.
        """
        if Live is not None and hasattr(clip, "add_new_notes"):
            spec = Live.Clip.MidiNoteSpecification
            clip.add_new_notes(tuple(
                spec(pitch=p, start_time=s, duration=d, velocity=v, mute=m)
                for p, s, d, v, m in tuples))
            return len(tuples)
        existing = []
        try:
            existing = list(clip.get_notes(0.0, 0, clip.length, 128))
        except Exception:
            pass
        clip.set_notes(tuple(existing + tuples))
        return len(tuples)

    def _do_set_notes(self, song, args):
        """Like add_notes but always replaces the clip's content."""
        args = dict(args)
        args["replace"] = True
        return self._do_add_notes(song, args)

    def _do_fire_clip(self, song, args):
        track = self._target_track(song, args)
        slot, _ = self._clip_slot(track, args)
        slot.fire()

    def _do_delete_clip(self, song, args):
        track = self._target_track(song, args)
        slot, _ = self._clip_slot(track, args)
        if slot.has_clip:
            slot.delete_clip()

    # ------------------------------------------------------------------
    # Samples (audio) - via the Browser API (Live 11/12)
    # ------------------------------------------------------------------
    def _do_load_sample(self, song, args):
        """
        args: track_index, file (path or file name inside your sample roots),
              slot (optional; defaults to first empty clip slot)
        """
        track = self._target_track(song, args)
        path = _find_sample(args["file"])
        if not path:
            raise ValueError("sample not found: %s (roots: %s)"
                             % (args["file"], os.pathsep.join(SAMPLE_ROOTS)))

        slot_index = int(args.get("slot", -1))
        if slot_index < 0:
            slot_index = 0
            for i, cs in enumerate(track.clip_slots):
                if not cs.has_clip:
                    slot_index = i
                    break
        slot = track.clip_slots[slot_index]
        if hasattr(slot, "insert_file"):
            slot.insert_file(path)
            return {"track": track.name, "slot": slot_index, "file": path}
        self.log_message(
            "ChatGPTBridge: insert_file unavailable in this Live version; "
            "sample located at %s - drop it on track %s slot %d"
            % (path, track.name, slot_index))
        self.show_message("Sample found: %s (drag to %s)"
                          % (os.path.basename(path), track.name))
        return {"track": track.name, "slot": slot_index, "file": path,
                "inserted": False}

    # ------------------------------------------------------------------
    # Devices / effects
    # ------------------------------------------------------------------
    def _browser_find(self, name):
        browser = self.application().browser
        needle = name.lower()
        best = None
        for root_name in ("instruments", "audio_effects", "midi_effects", "drums",
                          "sounds", "packs", "user_library"):
            root = getattr(browser, root_name, None)
            if root is None:
                continue
            stack = [root]
            seen = 0
            while stack and seen < 4000:
                node = stack.pop()
                for child in getattr(node, "children", None) or []:
                    seen += 1
                    child_name = (getattr(child, "name", "") or "").lower()
                    if getattr(child, "is_folder", False):
                        stack.append(child)
                        continue
                    if not getattr(child, "is_loadable", True):
                        continue
                    if child_name == needle or child_name == needle + ".adg":
                        return browser, child
                    if best is None and needle in child_name:
                        best = child
            if best is not None:
                return browser, best
        return browser, best

    def _do_load_device(self, song, args):
        """
        Load a built-in Ableton device onto a track by name.

        args: track_index|track, device_name (e.g. "Reverb", "Operator").
        device_name may be a list of candidates, tried in order, so a plan can
        ask for a Pack preset and fall back to a stock device.
        """
        track = self._target_track(song, args)
        names = args.get("device_name")
        names = list(names) if isinstance(names, (list, tuple)) else [names]
        names += list(args.get("fallbacks") or [])
        browser, item = None, None
        for candidate in names:
            if not candidate:
                continue
            browser, item = self._browser_find(str(candidate))
            if item is not None:
                break
        if item is None:
            raise ValueError("device not found in browser: %s" % ", ".join(
                str(n) for n in names if n))
        # load_item always targets the selected track, so select it first.
        song.view.selected_track = track
        browser.load_item(item)
        self.log_message("ChatGPTBridge: loaded device %s on %s" % (item.name, track.name))
        return {"track": track.name, "device": item.name}

    def _do_set_device_param(self, song, args):
        """
        args: track_index, device_index, param_name (substring),
              value (0..1 normalised, or a raw value inside the param range)
        """
        track = self._target_track(song, args)
        devices = track.devices
        d_index = int(args.get("device_index", 0))
        if d_index < 0 or d_index >= len(devices):
            raise ValueError("no device %d on '%s' (%d devices)"
                             % (d_index, track.name, len(devices)))
        device = devices[d_index]
        needle = args["param_name"].lower()
        for p in device.parameters:
            if needle in p.name.lower():
                v = float(args["value"])
                if p.min <= v <= p.max and not (0.0 <= v <= 1.0 and p.max > 1.0):
                    p.value = v
                else:
                    p.value = p.min + (p.max - p.min) * max(0.0, min(1.0, v))
                self.log_message("ChatGPTBridge: set %s.%s = %s" % (device.name, p.name, p.value))
                return {"device": device.name, "param": p.name, "value": p.value}
        raise ValueError("param %s not found on %s" % (args["param_name"], device.name))

    # ------------------------------------------------------------------
    # Automation (arrangement envelopes)
    # ------------------------------------------------------------------
    def _do_automate_mixer(self, song, args):
        """
        Stepped mixer automation.
        args: track_index, param ("volume"|"panning"),
              points: [{"time": beats, "value": 0..1}, ...]
        Uses the Live 11.3+/12 envelope API when available; otherwise applies
        the final value so the mix still lands somewhere sensible.
        """
        track = self._target_track(song, args)
        param_name = args.get("param", "volume")
        param = getattr(track.mixer_device, param_name, None)
        if param is None:
            raise ValueError("unknown mixer param: %s" % param_name)
        points = args.get("points", [])
        if not points:
            return {"points": 0}
        try:
            env = song.create_envelope(param)
            for pt in points:
                env.insert_step(float(pt["time"]), float(pt["value"]), 0.125)
            return {"points": len(points), "mode": "envelope"}
        except Exception as e:
            self.log_message("ChatGPTBridge: envelope API unavailable (%s); applying last value" % e)
            param.value = max(param.min, min(param.max, float(points[-1]["value"])))
            return {"points": len(points), "mode": "static"}

    # ------------------------------------------------------------------
    # Info / feedback to the agent
    # ------------------------------------------------------------------
    def _do_describe_set(self, song, args):
        info = {
            "bridge_version": BRIDGE_VERSION,
            "tempo": song.tempo,
            "is_playing": bool(song.is_playing),
            "signature": "%d/%d" % (song.signature_numerator, song.signature_denominator),
            "tracks": [
                {
                    "index": i,
                    "name": t.name,
                    "is_midi": bool(t.has_midi_input),
                    "mute": bool(t.mute),
                    "solo": bool(t.solo),
                    "devices": [d.name for d in t.devices],
                    "clips": [
                        {"slot": j, "name": cs.clip.name, "length": cs.clip.length}
                        for j, cs in enumerate(t.clip_slots) if cs.has_clip
                    ],
                }
                for i, t in enumerate(song.tracks)
            ],
            "return_tracks": [t.name for t in song.return_tracks],
        }
        self.log_message("ChatGPTBridge SET: " + json.dumps(info)[:4000])
        return info

    def _do_message(self, song, args):
        self.show_message(str(args.get("text", "")))
