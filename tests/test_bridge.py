# -*- coding: utf-8 -*-
"""End-to-end: planner -> UDP -> real remote script -> (simulated) Live."""

from ableton_agent import core


def _track(sim, name):
    return next(t for t in sim.song.tracks if t.name == name)


def test_ping_roundtrip(live):
    resp = core.send_command("ping", {}, wait_response=True, timeout=1.0, verbose=False)
    assert resp["status"] == "ok"
    assert resp["result"]["tracks"] == 4


def test_set_tempo_and_transport(live):
    core.send_plan({"commands": [
        {"action": "set_tempo", "args": {"bpm": 128}},
        {"action": "play", "args": {}},
    ]}, verbose=False, delay=0)
    assert live.song.tempo == 128.0
    assert live.song.is_playing is True


def test_named_track_is_created_and_addressable(live):
    results = core.send_plan({"commands": [
        {"action": "create_midi_track", "args": {"name": "Sub Bass"}},
        {"action": "create_clip", "args": {"track": "Sub Bass", "slot": 0, "length_beats": 4.0}},
        {"action": "add_notes", "args": {"track": "Sub Bass", "slot": 0, "notes": [
            {"pitch": 40, "start": 0.0, "length": 0.5, "velocity": 100}]}},
    ]}, verbose=False, delay=0)
    assert all(r["ok"] for r in results), results
    clip = _track(live, "Sub Bass").clip_slots[0].clip
    assert [n[0] for n in clip.notes] == [40]


def test_add_notes_appends_instead_of_replacing(live):
    core.send_plan({"commands": [
        {"action": "create_midi_track", "args": {"name": "Keys"}},
        {"action": "create_clip", "args": {"track": "Keys", "slot": 0, "length_beats": 4.0}},
        {"action": "add_notes", "args": {"track": "Keys", "slot": 0, "notes": [
            {"pitch": 60, "start": 0.0, "length": 1.0, "velocity": 90}]}},
        {"action": "add_notes", "args": {"track": "Keys", "slot": 0, "notes": [
            {"pitch": 64, "start": 1.0, "length": 1.0, "velocity": 90}]}},
    ]}, verbose=False, delay=0)
    clip = _track(live, "Keys").clip_slots[0].clip
    assert sorted(n[0] for n in clip.notes) == [60, 64]


def test_add_notes_replace_clears_existing(live):
    core.send_plan({"commands": [
        {"action": "create_midi_track", "args": {"name": "Keys"}},
        {"action": "create_clip", "args": {"track": "Keys", "slot": 0, "length_beats": 4.0}},
        {"action": "add_notes", "args": {"track": "Keys", "slot": 0, "notes": [
            {"pitch": 60, "start": 0.0, "length": 1.0, "velocity": 90}]}},
        {"action": "add_notes", "args": {"track": "Keys", "slot": 0, "replace": True, "notes": [
            {"pitch": 67, "start": 0.0, "length": 1.0, "velocity": 90}]}},
    ]}, verbose=False, delay=0)
    clip = _track(live, "Keys").clip_slots[0].clip
    assert [n[0] for n in clip.notes] == [67]


def test_track_minus_one_targets_last_created_track(live):
    core.send_plan({"commands": [
        {"action": "create_midi_track", "args": {"name": "Lead"}},
        {"action": "set_volume", "args": {"track": -1, "value": 0.5}},
    ]}, verbose=False, delay=0)
    assert _track(live, "Lead").mixer_device.volume.value == 0.5


def test_partial_track_name_matches(live):
    core.send_plan({"commands": [
        {"action": "create_midi_track", "args": {"name": "Rolling Bass"}},
        {"action": "set_pan", "args": {"track": "bass", "value": -0.4}},
    ]}, verbose=False, delay=0)
    assert _track(live, "Rolling Bass").mixer_device.panning.value == -0.4


def test_unknown_track_returns_error_ack(live):
    results = core.send_plan({"commands": [
        {"action": "set_volume", "args": {"track": "Nope", "value": 0.5}},
    ]}, verbose=False, delay=0)
    assert results[0]["ok"] is False
    assert "Nope" in results[0]["response"]["error"]


def test_load_device_falls_back_through_candidates(live):
    results = core.send_plan({"commands": [
        {"action": "create_midi_track", "args": {"name": "Drums"}},
        {"action": "load_device", "args": {"track": "Drums",
                                           "device_name": ["Kit-Core 909", "Drum Rack"]}},
    ]}, verbose=False, delay=0)
    assert all(r["ok"] for r in results), results
    assert [d.name for d in _track(live, "Drums").devices] == ["Drum Rack"]


def test_describe_set_reports_tracks(live):
    core.send_plan({"commands": [{"action": "create_midi_track", "args": {"name": "Pad"}}]},
                   verbose=False, delay=0)
    info = core.describe_set(timeout=1.0)
    assert info["tempo"] == 120.0
    assert "Pad" in [t["name"] for t in info["tracks"]]


def test_full_offline_plan_builds_a_playable_set(live):
    plan = core.get_plan("tech house at 126 bpm", verbose=False)
    results = core.send_plan(plan, verbose=False, delay=0)
    assert all(r["ok"] for r in results), [r for r in results if not r["ok"]]

    built = {t.name: t for t in live.song.tracks[4:]}
    assert set(built) == {"Kick", "Clap", "Sub Bass", "Chords", "Hi-Hats"}
    for track in built.values():
        assert track.devices, "%s has no instrument and would be silent" % track.name
        assert track.clip_slots[0].has_clip
        assert track.clip_slots[0].clip.notes
    assert live.song.tempo == 126.0
    assert live.song.is_playing is True
