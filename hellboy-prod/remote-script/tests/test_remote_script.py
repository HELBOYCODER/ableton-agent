# -*- coding: utf-8 -*-
"""Load the remote script the way Live does (as a package) against a fake LOM.

Standard library only:  python -m unittest discover -s remote-script/tests
"""

import contextlib
import json
import os
import re
import socket
import sys
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "remote-script"))


# ------------------------------------------------------------------ fake Live
class NoteSpec(object):
    def __init__(self, pitch, start_time, duration, velocity, mute):
        self.pitch, self.start_time, self.duration = pitch, start_time, duration
        self.velocity, self.mute = velocity, mute


class Param(object):
    def __init__(self, name, value=0.0, low=0.0, high=1.0):
        self.name, self.value, self.min, self.max = name, value, low, high
        self.is_quantized = False


class Clip(object):
    def __init__(self, length):
        self.length = float(length)
        self.name = ""
        self.is_midi_clip = True
        self.notes = []

    def get_notes_extended(self, pitch, pitch_span, start, span):
        return [n for n in self.notes
                if pitch <= n.pitch < pitch + pitch_span and start <= n.start_time < start + span]

    def remove_notes_extended(self, pitch, pitch_span, start, span):
        keep = set(id(n) for n in self.get_notes_extended(pitch, pitch_span, start, span))
        self.notes = [n for n in self.notes if id(n) not in keep]

    def add_new_notes(self, specs):
        self.notes.extend(specs)


class Slot(object):
    def __init__(self):
        self.clip = None

    @property
    def has_clip(self):
        return self.clip is not None

    def create_clip(self, length):
        self.clip = Clip(length)
        return self.clip

    def delete_clip(self):
        self.clip = None


class Mixer(object):
    def __init__(self):
        self.volume = Param("Volume", 0.85)
        self.panning = Param("Pan", 0.0, -1.0, 1.0)
        self.sends = []


class Device(object):
    def __init__(self, name):
        self.name = name
        self.class_name = name
        self.parameters = [Param("Device On", 1.0), Param("Cutoff", 0.0, 20.0, 20000.0)]


class Track(object):
    def __init__(self, name):
        self.name = name
        self.has_midi_input = True
        self.mixer_device = Mixer()
        self.devices = [Device("Filter")]
        self.clip_slots = [Slot() for _ in range(4)]
        self.color_index = 0


class Song(object):
    def __init__(self):
        self.tempo = 120.0
        self.signature_numerator = 4
        self.signature_denominator = 4
        self.is_playing = False
        self.tracks = [Track("Drums"), Track("Bass")]
        self.return_tracks = []
        self.scenes = []
        self.master_track = Track("Master")
        self.view = types.SimpleNamespace(selected_track=self.tracks[0])
        self.undo_steps = []

    def begin_undo_step(self):
        self.undo_steps.append("begin")

    def end_undo_step(self):
        self.undo_steps.append("end")


def install_fakes():
    live = types.ModuleType("Live")
    live.Clip = types.SimpleNamespace(MidiNoteSpecification=NoteSpec)
    live.Application = types.SimpleNamespace(get_application=lambda: None)
    sys.modules["Live"] = live

    framework = types.ModuleType("_Framework")
    surface_module = types.ModuleType("_Framework.ControlSurface")

    class ControlSurface(object):
        def __init__(self, c_instance):
            self._song = c_instance
            self.scheduled = []

        def component_guard(self):
            return contextlib.contextmanager(lambda: (yield))()

        def schedule_message(self, delay, callback):
            self.scheduled.append(callback)

        def log_message(self, *args):
            pass

        def song(self):
            return self._song

        def disconnect(self):
            pass

    surface_module.ControlSurface = ControlSurface
    framework.ControlSurface = surface_module
    sys.modules["_Framework"] = framework
    sys.modules["_Framework.ControlSurface"] = surface_module


install_fakes()
os.environ["HELLBOY_PORT"] = "0"  # ephemeral port for the test server
import HellboyProd  # noqa: E402  (must come after the fakes)


class RemoteScriptTest(unittest.TestCase):
    def setUp(self):
        self.song = Song()
        self.surface = HellboyProd.create_instance(self.song)

    def tearDown(self):
        self.surface.disconnect()

    def call(self, method, **params):
        return self.surface._dispatch(method, params)

    def test_hello_lists_every_handler(self):
        info = self.call("hello")
        self.assertEqual(info["product"], "Hellboy Prod")
        self.assertIn("quickloop_generate", info["methods"])

    def test_bridge_registry_matches_handlers(self):
        with open(os.path.join(ROOT, "bridge", "src", "registry.ts")) as handle:
            registry = set(re.findall(r'method: "([a-z_]+)"', handle.read()))
        internal = {"hello", "ping", "shutdown"}
        self.assertEqual(registry, set(self.call("hello")["methods"]) - internal)

    def test_socket_round_trip_runs_on_tick(self):
        client = socket.create_connection(("127.0.0.1", self.surface._port), timeout=5)
        try:
            client.sendall(b'{"id":7,"method":"session_state","params":{}}\n')
            client.setblocking(False)
            data = b""
            deadline = time.time() + 5
            while b"\n" not in data and time.time() < deadline:
                self.surface._tick()
                try:
                    data += client.recv(65536)
                except (BlockingIOError, socket.error):
                    time.sleep(0.01)
            reply = json.loads(data.decode("utf-8"))
        finally:
            client.close()
        self.assertEqual(reply["id"], 7)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["result"]["track_count"], 2)

    def test_notes_round_trip(self):
        self.call("clip_create", track=0, slot=0, length=4)
        self.call("notes_set", track=0, slot=0, notes=[
            {"pitch": 36, "start": 0, "dur": 0.5, "vel": 100},
            {"pitch": 43, "start": 1, "dur": 0.5, "vel": 90},
        ])
        self.assertEqual(self.call("notes_get", track=0, slot=0)["count"], 2)
        self.call("notes_transpose", track=0, slot=0, semitones=12)
        pitches = sorted(n["pitch"] for n in self.call("notes_get", track=0, slot=0)["notes"])
        self.assertEqual(pitches, [48, 55])

    def test_notes_range_clamps_without_folding(self):
        self.call("clip_create", track=0, slot=0, length=4)
        self.call("notes_set", track=0, slot=0, notes=[{"pitch": 20, "start": 0, "dur": 1}])
        self.call("notes_range", track=0, slot=0, low=36, high=48, fold=False)
        self.assertEqual(self.call("notes_get", track=0, slot=0)["notes"][0]["pitch"], 36)

    def test_quickloop_keeps_the_source_clip(self):
        self.call("clip_create", track=0, slot=0, length=4, name="loop")
        self.call("notes_set", track=0, slot=0, notes=[
            {"pitch": 36 + i, "start": i * 0.5, "dur": 0.25} for i in range(8)])
        result = self.call("quickloop_generate", track=0, slot=0, seed=3)
        self.assertEqual(result["destination"], [0, 1])
        self.assertEqual(self.call("notes_get", track=0, slot=0)["count"], 8)
        self.assertEqual(self.call("notes_get", track=0, slot=1)["count"], 8)
        with self.assertRaises(ValueError):
            self.call("quickloop_generate", track=0, slot=0, target_slot=0)

    def test_normalized_param_maps_to_range(self):
        result = self.call("device_set_param", track=0, device=0, name="Cutoff",
                           value=0.5, normalized=True)
        self.assertAlmostEqual(result["value"], 10010.0)

    # ------------------------------------------------------------ theory
    def notes(self, track=0, slot=0):
        return sorted(self.call("notes_get", track=track, slot=slot)["notes"],
                      key=lambda n: (n["start"], n["pitch"]))

    def test_chords_write_diatonic_progression(self):
        self.call("clip_create", track=0, slot=0, length=16)
        result = self.call("notes_chords", track=0, slot=0, root="A", scale="minor",
                           progression=[1, 6, 3, 7], octave=3)
        self.assertEqual([c["notes"] for c in result["chords"]], [
            ["A3", "C4", "E4"], ["F4", "A4", "C5"], ["C4", "E4", "G4"], ["G4", "B4", "D5"]])
        self.assertEqual(self.notes()[0]["pitch"], 69)  # A3 in Ableton = MIDI 69
        self.assertEqual(result["written"], 12)
        sevenths = self.call("notes_chords", track=0, slot=0, root="C", scale="major",
                             progression=[2], size=4)
        self.assertEqual(sevenths["chords"][0]["notes"], ["D3", "F3", "A3", "C4"])

    def test_detect_key_finds_a_minor(self):
        self.call("clip_create", track=0, slot=0, length=16)
        self.call("notes_chords", track=0, slot=0, root="A", scale="minor",
                  progression=[1, 4, 5, 1])
        self.assertEqual(self.call("notes_detect_key", track=0, slot=0)["key"]["root"], "A")

    def test_scale_fit_snaps_out_of_key_notes(self):
        self.call("clip_create", track=0, slot=0, length=4)
        self.call("notes_set", track=0, slot=0, notes=[
            {"pitch": 61, "start": 0, "dur": 1}, {"pitch": 64, "start": 1, "dur": 1}])
        result = self.call("notes_scale_fit", track=0, slot=0, root="C", scale="major")
        self.assertEqual(result["moved"], 1)
        self.assertEqual([n["pitch"] for n in self.notes()], [60, 64])

    def test_swing_moves_only_offbeats(self):
        self.call("clip_create", track=0, slot=0, length=1)
        self.call("notes_set", track=0, slot=0, notes=[
            {"pitch": 42, "start": i * 0.25, "dur": 0.1} for i in range(4)])
        self.call("notes_swing", track=0, slot=0, preset="mpc_66")
        starts = [n["start"] for n in self.notes()]
        self.assertAlmostEqual(starts[0], 0.0)
        self.assertAlmostEqual(starts[1], 0.33, places=2)
        self.assertAlmostEqual(starts[2], 0.5)

    def test_arpeggiate_turns_a_chord_into_steps(self):
        self.call("clip_create", track=0, slot=0, length=1)
        self.call("notes_set", track=0, slot=0, notes=[
            {"pitch": p, "start": 0, "dur": 1} for p in (60, 64, 67)])
        self.call("notes_arpeggiate", track=0, slot=0, rate=0.25, style="up")
        self.assertEqual([n["pitch"] for n in self.notes()], [60, 64, 67, 60])

    def test_each_call_is_one_undo_step(self):
        self.song.undo = lambda: None
        self.call("session_set_tempo", tempo=128)
        self.call("session_undo")  # must not open an undo step of its own
        self.assertEqual(self.song.undo_steps, ["begin", "end"])
        with self.assertRaises(ValueError):
            self.call("notes_get", track=0, slot=0)  # empty slot still closes the step
        self.assertEqual(self.song.undo_steps, ["begin", "end", "begin", "end"])

    def test_unknown_method_is_an_error_not_a_crash(self):
        with self.assertRaises(NameError):
            self.call("does_not_exist")


if __name__ == "__main__":
    unittest.main()
