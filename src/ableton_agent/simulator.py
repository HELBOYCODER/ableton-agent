# -*- coding: utf-8 -*-
"""Offline Ableton Live simulator.

Runs the *real* ChatGPTBridge Remote Script against an in-memory model of the
Live Object Model, so the whole pipeline (planner -> UDP -> bridge -> LOM) can
be exercised, tested and demoed without Ableton Live installed.

    ableton-agent simulate          # start a fake Live on udp://127.0.0.1:9000
    ableton-agent run "techno 130"  # in another shell: really "builds" a track
"""

import contextlib
import json
import os
import sys
import threading
import time
import types


# ---------------------------------------------------------------------------
# Minimal Live Object Model mock
# ---------------------------------------------------------------------------
class FakeParameter(object):
    def __init__(self, name, value=0.85, minimum=0.0, maximum=1.0):
        self.name = name
        self.value = value
        self.min = minimum
        self.max = maximum


class FakeMixer(object):
    def __init__(self):
        self.volume = FakeParameter("Volume", 0.85)
        self.panning = FakeParameter("Pan", 0.0, -1.0, 1.0)
        self.sends = []


class FakeClip(object):
    def __init__(self, name, length):
        self.name = name
        self.length = length
        self.notes = []  # (pitch, start, duration, velocity, mute)

    def add_new_notes(self, specs):
        for spec in specs:
            self.notes.append((spec.pitch, spec.start_time, spec.duration,
                               spec.velocity, spec.mute))

    def get_notes(self, from_time, from_pitch, time_span, pitch_span):
        return tuple(self.notes)

    def set_notes(self, notes):
        self.notes = list(notes)

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        self.notes = []


class FakeClipSlot(object):
    def __init__(self, track, index):
        self._track = track
        self._index = index
        self.clip = None
        self.fired = False

    @property
    def has_clip(self):
        return self.clip is not None

    def create_clip(self, length):
        if self.clip is not None:
            raise RuntimeError("slot already has a clip")
        self.clip = FakeClip("%s %d" % (self._track.name, self._index + 1), length)

    def delete_clip(self):
        self.clip = None

    def insert_file(self, path):
        self.clip = FakeClip(os.path.basename(path), 4.0)

    def fire(self):
        self.fired = True


class FakeView(object):
    def __init__(self):
        self.selected_track = None


class FakeDevice(object):
    def __init__(self, name):
        self.name = name
        self.parameters = [FakeParameter("Device On", 1.0),
                           FakeParameter("Dry/Wet", 0.5)]


class FakeTrack(object):
    def __init__(self, name, is_midi=True, slots=8):
        self.name = name
        self.has_midi_input = is_midi
        self.mute = False
        self.solo = False
        self.arm = False
        self.can_be_armed = True
        self.devices = []
        self.mixer_device = FakeMixer()
        self.view = FakeView()
        self.clip_slots = [FakeClipSlot(self, i) for i in range(slots)]


class FakeSong(object):
    """A fresh Live set: 2 MIDI + 2 audio tracks, exactly like Live's default."""

    def __init__(self):
        self.tempo = 120.0
        self.is_playing = False
        self.signature_numerator = 4
        self.signature_denominator = 4
        self.tracks = [
            FakeTrack("1 MIDI", True),
            FakeTrack("2 MIDI", True),
            FakeTrack("3 Audio", False),
            FakeTrack("4 Audio", False),
        ]
        self.return_tracks = []
        self.view = FakeView()

    def create_midi_track(self, index=-1):
        self._insert(FakeTrack("%d MIDI" % (len(self.tracks) + 1), True), index)

    def create_audio_track(self, index=-1):
        self._insert(FakeTrack("%d Audio" % (len(self.tracks) + 1), False), index)

    def _insert(self, track, index):
        if index is None or index < 0 or index > len(self.tracks):
            self.tracks.append(track)
        else:
            self.tracks.insert(index, track)

    def create_return_track(self):
        self.return_tracks.append(FakeTrack("Return %c" % (65 + len(self.return_tracks)), False))
        for track in self.tracks:
            track.mixer_device.sends.append(FakeParameter("Send", 0.0))

    def delete_track(self, index):
        del self.tracks[index]


class FakeBrowserItem(object):
    def __init__(self, name):
        self.name = name
        self.is_folder = False
        self.is_loadable = True
        self.children = []


class FakeBrowser(object):
    """A handful of stock devices so load_device can be exercised."""

    def __init__(self, song):
        self._song = song
        self.instruments = FakeBrowserItem("Instruments")
        self.instruments.is_folder = True
        self.instruments.children = [FakeBrowserItem(n) for n in
                                     ("Operator", "Drum Rack", "Wavetable", "Analog")]
        self.audio_effects = FakeBrowserItem("Audio Effects")
        self.audio_effects.is_folder = True
        self.audio_effects.children = [FakeBrowserItem(n) for n in
                                       ("Reverb", "Delay", "EQ Eight", "Glue Compressor",
                                        "Compressor", "Auto Filter", "Saturator")]
        self.midi_effects = FakeBrowserItem("MIDI Effects")
        self.midi_effects.is_folder = True
        self.midi_effects.children = [FakeBrowserItem("Arpeggiator")]

    def load_item(self, item):
        track = self._song.view.selected_track or self._song.tracks[0]
        track.devices.append(FakeDevice(item.name))


class FakeApplication(object):
    def __init__(self, song):
        self.browser = FakeBrowser(song)


# ---------------------------------------------------------------------------
# _Framework / Live stubs so the real remote script can be imported here
# ---------------------------------------------------------------------------
class _MidiNoteSpecification(object):
    def __init__(self, pitch=60, start_time=0.0, duration=0.25, velocity=100, mute=False):
        self.pitch = pitch
        self.start_time = start_time
        self.duration = duration
        self.velocity = velocity
        self.mute = mute


def _install_stub_modules():
    """Register fake `_Framework` and `Live` modules (idempotent)."""
    if "_Framework.ControlSurface" not in sys.modules:
        framework = types.ModuleType("_Framework")
        cs_module = types.ModuleType("_Framework.ControlSurface")

        class ControlSurface(object):
            def __init__(self, c_instance):
                self._c_instance = c_instance
                self.messages = []

            def song(self):
                return self._c_instance.song()

            def application(self):
                return self._c_instance.application()

            def log_message(self, message):
                self.messages.append(message)

            def show_message(self, message):
                self.messages.append(message)

            @contextlib.contextmanager
            def component_guard(self):
                yield

            def update_display(self):
                pass

            def disconnect(self):
                pass

        cs_module.ControlSurface = ControlSurface
        framework.ControlSurface = cs_module
        sys.modules["_Framework"] = framework
        sys.modules["_Framework.ControlSurface"] = cs_module

    if "Live" not in sys.modules:
        live = types.ModuleType("Live")
        clip_module = types.ModuleType("Live.Clip")
        clip_module.MidiNoteSpecification = _MidiNoteSpecification
        live.Clip = clip_module
        sys.modules["Live"] = live
        sys.modules["Live.Clip"] = clip_module


class FakeCInstance(object):
    def __init__(self, song):
        self._song = song
        self._application = FakeApplication(song)

    def song(self):
        return self._song

    def application(self):
        return self._application


class LiveSimulator(object):
    """A fake Ableton Live driving the real ChatGPTBridge remote script."""

    def __init__(self, song=None, host=None, port=None):
        _install_stub_modules()
        self.song = song or FakeSong()
        from .remote_script import ChatGPTBridge as bridge_module
        # HOST/PORT are module constants read at import time; override them so
        # repeated simulators (e.g. in tests) can use different ports.
        if host is not None:
            bridge_module.HOST = host
        if port is not None:
            bridge_module.PORT = int(port)
        self._module = bridge_module
        self.bridge = bridge_module.ChatGPTBridge(FakeCInstance(self.song))
        self._stop = threading.Event()
        self._pump = None

    @property
    def host(self):
        return self._module.HOST

    @property
    def port(self):
        return self._module.PORT

    def pump(self):
        """Process every queued command (this is Live's main thread)."""
        self.bridge.update_display()

    def start(self, interval=0.01):
        """Pump in a background thread, mimicking Live's display timer."""
        def loop():
            while not self._stop.is_set():
                self.pump()
                time.sleep(interval)
        self._pump = threading.Thread(target=loop)
        self._pump.daemon = True
        self._pump.start()
        self.wait_until_listening()
        return self

    def wait_until_listening(self, timeout=5.0):
        """Block until the bridge socket is bound (UDP drops early packets)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if getattr(self.bridge, "_sock", None) is not None:
                return True
            time.sleep(0.01)
        raise RuntimeError("simulator bridge never bound udp://%s:%d"
                           % (self.host, self.port))

    def stop(self):
        self._stop.set()
        if self._pump:
            self._pump.join(timeout=2.0)
        self.bridge.disconnect()

    def summary(self):
        return {
            "tempo": self.song.tempo,
            "is_playing": self.song.is_playing,
            "tracks": [
                {
                    "name": t.name,
                    "is_midi": t.has_midi_input,
                    "devices": [d.name for d in t.devices],
                    "volume": round(t.mixer_device.volume.value, 3),
                    "clips": [
                        {"slot": i, "length": cs.clip.length, "notes": len(cs.clip.notes)}
                        for i, cs in enumerate(t.clip_slots) if cs.has_clip
                    ],
                }
                for t in self.song.tracks
            ],
        }


def run_simulator(port=None, host="127.0.0.1", verbose=True):
    """Run a fake Live until Ctrl+C, printing the set state as it changes."""
    sim = LiveSimulator(host=host, port=port).start()
    if verbose:
        print("ableton-agent simulator: fake Live listening on udp://%s:%d"
              % (sim.host, sim.port))
        print("Run `ableton-agent run \"tech house at 126 bpm\"` in another shell.")
        print("Ctrl+C to stop.\n")
    last = None
    try:
        while True:
            time.sleep(0.25)
            if not verbose:
                continue
            current = json.dumps(sim.summary(), sort_keys=True)
            if current != last:
                last = current
                print(json.dumps(sim.summary(), indent=2))
    except KeyboardInterrupt:
        print("\nsimulator stopped.")
    finally:
        sim.stop()
    return sim
