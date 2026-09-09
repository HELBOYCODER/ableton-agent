# -*- coding: utf-8 -*-
"""
ChatGPTBridge - Ableton Live MIDI Remote Script
================================================
A Control Surface that listens for JSON commands over UDP (127.0.0.1:9000)
and executes them against the Live Object Model (LOM).

Commands are produced by agent.py (the ChatGPT layer). Each command:
    {"action": "<name>", "args": {...}}

Place this folder (ChatGPTBridge/) inside Ableton's MIDI Remote Scripts
directory, then select "ChatGPTBridge" as a Control Surface in
Preferences > Link/Tempo/MIDI.
"""

from __future__ import absolute_import, print_function

import json
import socket
import threading
import os

from _Framework.ControlSurface import ControlSurface

HOST = "127.0.0.1"
PORT = 9000

# Optional: root folder of your sample library (also configurable from agent.py)
SAMPLE_ROOTS = [
    os.path.expanduser("~/Samples"),
    os.path.expanduser("~/Music/Samples"),
]


def _find_sample(filename):
    """Search the sample roots (recursively, depth-limited) for a file name."""
    filename = filename.replace("\\", "/")
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename
    base = os.path.basename(filename)
    for root in SAMPLE_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth > 4:
                continue
            for f in filenames:
                if f.lower() == base.lower():
                    return os.path.join(dirpath, f)
    return None


class ChatGPTBridge(ControlSurface):

    def __init__(self, c_instance):
        super(ChatGPTBridge, self).__init__(c_instance)
        self._stop = False
        self._sock = None
        with self.component_guard():
            pass
        t = threading.Thread(target=self._listen)
        t.daemon = True
        t.start()
        self.log_message("ChatGPTBridge: listening on udp://%s:%d" % (HOST, PORT))
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
    # UDP listener thread -> marshal into Live's main thread
    # ------------------------------------------------------------------
    def _listen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.settimeout(1.0)
        self._sock = s
        while not self._stop:
            try:
                data, _addr = s.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception:
                break
            try:
                cmd = json.loads(data.decode("utf-8"))
                self.schedule_message(0, self._execute, cmd)
            except Exception as e:
                self.log_message("ChatGPTBridge: bad packet: %s" % e)

    # ------------------------------------------------------------------
    # Command dispatcher (runs on Live's main thread)
    # ------------------------------------------------------------------
    def _execute(self, cmd):
        song = self.song()
        action = cmd.get("action")
        args = cmd.get("args", {}) or {}
        try:
            handler = getattr(self, "_do_" + action, None)
            if handler is None:
                self.log_message("ChatGPTBridge: unknown action %s" % action)
                return
            handler(song, args)
            self.log_message("ChatGPTBridge: OK %s %s" % (action, args))
        except Exception as e:
            self.log_message("ChatGPTBridge: ERROR %s -> %s" % (action, e))

    # ------------------------------------------------------------------
    # Project / transport
    # ------------------------------------------------------------------
    def _do_set_tempo(self, song, args):
        song.tempo = float(args.get("bpm", 124.0))

    def _do_play(self, song, args):
        song.is_playing = True

    def _do_stop(self, song, args):
        song.is_playing = False

    def _do_rename_project(self, song, args):
        self.show_message("Project: %s" % args.get("name", ""))

    # ------------------------------------------------------------------
    # Tracks
    # ------------------------------------------------------------------
    def _do_create_midi_track(self, song, args):
        idx = int(args.get("index", -1))
        song.create_midi_track(idx)
        name = args.get("name")
        if name:
            track = song.tracks[idx if idx >= 0 else len(song.tracks) - 1]
            track.name = name

    def _do_create_audio_track(self, song, args):
        idx = int(args.get("index", -1))
        song.create_audio_track(idx)
        name = args.get("name")
        if name:
            track = song.tracks[idx if idx >= 0 else len(song.tracks) - 1]
            track.name = name

    def _do_create_return_track(self, song, args):
        song.create_return_track()
        name = args.get("name")
        if name:
            song.return_tracks[len(song.return_tracks) - 1].name = name

    def _do_delete_track(self, song, args):
        song.delete_track(int(args["track_index"]))

    def _do_rename_track(self, song, args):
        song.tracks[int(args["track_index"])].name = args["name"]

    # ------------------------------------------------------------------
    # Mixer
    # ------------------------------------------------------------------
    def _track(self, song, idx):
        idx = int(idx)
        if idx < 0 or idx >= len(song.tracks):
            raise ValueError("track_index %s out of range (%d tracks)" % (idx, len(song.tracks)))
        return song.tracks[idx]

    def _do_set_volume(self, song, args):
        track = self._track(song, args["track_index"])
        # value: 0.0 - 1.0 (1.0 = 0 dB)
        track.mixer_device.volume.value = max(0.0, min(1.0, float(args["value"])))

    def _do_set_pan(self, song, args):
        track = self._track(song, args["track_index"])
        track.mixer_device.panning.value = max(-1.0, min(1.0, float(args["value"])))

    def _do_mute_track(self, song, args):
        self._track(song, args["track_index"]).mute = bool(args.get("mute", True))

    def _do_solo_track(self, song, args):
        self._track(song, args["track_index"]).solo = bool(args.get("solo", True))

    def _do_arm_track(self, song, args):
        track = self._track(song, args["track_index"])
        if track.can_be_armed:
            track.arm = bool(args.get("arm", True))

    def _do_add_send(self, song, args):
        """Route a track to a return bus. args: track_index, bus_index, amount(0-1)."""
        track = self._track(song, args["track_index"])
        bus = int(args["bus_index"])
        sends = track.mixer_device.sends
        if bus < len(sends):
            sends[bus].value = max(0.0, min(1.0, float(args.get("amount", 0.3))))

    # ------------------------------------------------------------------
    # Clips & notes (MIDI)
    # ------------------------------------------------------------------
    def _do_create_clip(self, song, args):
        """args: track_index, slot, length_beats"""
        track = self._track(song, args["track_index"])
        slot = track.clip_slots[int(args["slot"])]
        length = float(args.get("length_beats", 4.0))
        slot.create_clip(length)

    def _do_add_notes(self, song, args):
        """
        args: track_index, slot,
              notes: [{"pitch":60,"start":0.0,"length":0.25,"velocity":100}, ...]
        start/length in beats.
        """
        track = self._track(song, args["track_index"])
        clip = track.clip_slots[int(args["slot"])].clip
        if clip is None:
            raise ValueError("no clip in slot - call create_clip first")
        tuples = []
        for n in args["notes"]:
            tuples.append((
                int(n["pitch"]),
                float(n["start"]),
                float(n["length"]),
                int(n.get("velocity", 100)),
                False,  # muted
            ))
        if tuples:
            clip.set_notes(tuple(tuples))

    def _do_fire_clip(self, song, args):
        track = self._track(song, args["track_index"])
        track.clip_slots[int(args["slot"])].fire()

    def _do_delete_clip(self, song, args):
        track = self._track(song, args["track_index"])
        slot = track.clip_slots[int(args["slot"])]
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
        track = self._track(song, args["track_index"])
        path = _find_sample(args["file"])
        if not path:
            raise ValueError("sample not found: %s" % args["file"])

        browser_item = None
        try:
            # Live 11/12 browser API
            browser = self.application().browser
            browser_item = browser.load_item(path) if hasattr(browser, "load_item") else None
        except Exception:
            browser_item = None

        slot_index = int(args.get("slot", -1))
        if slot_index < 0:
            for i, cs in enumerate(track.clip_slots):
                if not cs.has_clip:
                    slot_index = i
                    break

        if browser_item is not None:
            # Some Live versions allow dropping via browser; otherwise we log.
            self.log_message("ChatGPTBridge: browser load for %s" % path)

        # Reliable cross-version approach: use the view to drag is not possible
        # from a Remote Script, so we use create_audio_clip-like behaviour when
        # available (Live 12 exposes clip_slot.insert_file on audio tracks).
        slot = track.clip_slots[slot_index]
        if hasattr(slot, "insert_file"):
            slot.insert_file(path)
        else:
            self.log_message(
                "ChatGPTBridge: insert_file not available in this Live version; "
                "sample located at %s - drop it on track %d slot %d"
                % (path, int(args["track_index"]), slot_index))
            self.show_message("Sample found: %s (drag to track %d)" % (os.path.basename(path), int(args["track_index"])))

    # ------------------------------------------------------------------
    # Devices / effects
    # ------------------------------------------------------------------
    def _do_load_device(self, song, args):
        """
        Load a built-in Ableton device onto a track by browser URI or name.
        args: track_index, device_name (e.g. "Reverb", "Delay", "Glue Compressor")
        Works on Live 11/12 by searching the browser 'audio_effects' / 'instruments'.
        """
        track = self._track(song, args["track_index"])
        name = args["device_name"].lower()
        browser = self.application().browser
        found = None
        for root_name in ("audio_effects", "instruments", "midi_effects"):
            try:
                root = getattr(browser, root_name)
            except Exception:
                continue
            stack = [root]
            while stack and found is None:
                node = stack.pop()
                for child in getattr(node, "children", []) or []:
                    if not getattr(child, "is_folder", False) and name in child.name.lower():
                        found = child
                        break
                    if getattr(child, "is_folder", False):
                        stack.append(child)
            if found is not None:
                break
        if found is None:
            raise ValueError("device not found in browser: %s" % args["device_name"])
        if hasattr(track.view, "insert_device"):
            track.view.insert_device(found)
        else:
            browser.hotswap_target = track
            self.log_message("ChatGPTBridge: hotswap set for %s" % args["device_name"])
        self.log_message("ChatGPTBridge: loaded device %s on track %s" % (found.name, args["track_index"]))

    def _do_set_device_param(self, song, args):
        """
        args: track_index, device_index, param_name (substring), value (raw device range)
        """
        track = self._track(song, args["track_index"])
        device = track.devices[int(args["device_index"])]
        needle = args["param_name"].lower()
        for p in device.parameters:
            if needle in p.name.lower():
                rng = p.max - p.min
                v = float(args["value"])
                p.value = p.min + rng * v if 0.0 <= v <= 1.0 else v
                self.log_message("ChatGPTBridge: set %s.%s" % (device.name, p.name))
                return
        raise ValueError("param %s not found on %s" % (args["param_name"], device.name))

    # ------------------------------------------------------------------
    # Automation (arrangement envelopes)
    # ------------------------------------------------------------------
    def _do_automate_mixer(self, song, args):
        """
        Simple stepped volume automation on the arrangement.
        args: track_index, param ("volume"|"panning"),
              points: [{"time": beats, "value": 0..1}, ...]
        Uses Live 11+ envelope API when available; otherwise falls back to
        scheduling mixer values (session-style).
        """
        track = self._track(song, args["track_index"])
        param_name = args.get("param", "volume")
        param = getattr(track.mixer_device, param_name)
        points = args.get("points", [])
        if not points:
            return
        try:
            env = song.create_envelope(param)  # Live 11.3+/12
            first = points[0]
            env.insert_step(float(first["time"]), float(first["value"]), 0.125)
            for pt in points[1:]:
                env.insert_step(float(pt["time"]), float(pt["value"]), 0.125)
        except Exception as e:
            self.log_message("ChatGPTBridge: envelope API unavailable (%s); applying last value" % e)
            param.value = max(param.min, min(param.max, float(points[-1]["value"])))

    # ------------------------------------------------------------------
    # Info / feedback to the agent
    # ------------------------------------------------------------------
    def _do_describe_set(self, song, args):
        info = {
            "tempo": song.tempo,
            "tracks": [
                {
                    "index": i,
                    "name": t.name,
                    "is_midi": t.has_midi_input,
                    "devices": [d.name for d in t.devices],
                    "clips": [
                        {"slot": j, "name": cs.clip.name if cs.has_clip else None}
                        for j, cs in enumerate(t.clip_slots) if cs.has_clip
                    ],
                }
                for i, t in enumerate(song.tracks)
            ],
            "return_tracks": [t.name for t in song.return_tracks],
        }
        self.log_message("ChatGPTBridge SET: " + json.dumps(info)[:4000])

    def _do_message(self, song, args):
        self.show_message(str(args.get("text", "")))
