# -*- coding: utf-8 -*-
"""Planner, JSON extraction and plan normalization."""

import json

import pytest

from ableton_agent import core


def test_extract_json_plain():
    assert core.extract_json('{"commands": []}') == {"commands": []}


def test_extract_json_fenced_with_prose():
    text = 'Sure! Here you go:\n```json\n{"commands": [{"action": "play", "args": {}}]}\n```\nEnjoy.'
    assert core.extract_json(text)["commands"][0]["action"] == "play"


def test_extract_json_nested_braces():
    text = 'blah {"commands": [{"action": "add_notes", "args": {"notes": [{"pitch": 60}]}}]} trailing'
    plan = core.extract_json(text)
    assert plan["commands"][0]["args"]["notes"] == [{"pitch": 60}]


def test_extract_json_invalid_raises():
    with pytest.raises(ValueError):
        core.extract_json("no json at all")


def test_normalize_plan_accepts_bare_list():
    plan = core.normalize_plan([{"action": "play"}])
    assert plan["commands"] == [{"action": "play", "args": {}}]


def test_normalize_plan_resolves_aliases_and_drops_unknown():
    plan = core.normalize_plan({"commands": [
        {"action": "tempo", "args": {"bpm": "128"}},
        {"action": "definitely_not_real", "args": {}},
    ]})
    assert plan["commands"] == [{"action": "set_tempo", "args": {"bpm": 128.0}}]
    assert plan["dropped"] == ["definitely_not_real"]


def test_normalize_plan_drops_commands_missing_required_args():
    plan = core.normalize_plan({"commands": [{"action": "set_tempo", "args": {}}]})
    assert plan["commands"] == []


def test_normalize_plan_coerces_notes():
    plan = core.normalize_plan({"commands": [{"action": "add_notes", "args": {
        "track": "Kick",
        "notes": [{"pitch": "36", "start": "0", "length": 0.25, "velocity": 400}],
    }}]})
    note = plan["commands"][0]["args"]["notes"][0]
    assert note == {"pitch": 36, "start": 0.0, "length": 0.25, "velocity": 127}


def test_normalize_plan_is_idempotent():
    once = core.normalize_plan({"commands": [{"action": "tempo", "args": {"bpm": 128}}]})
    assert core.normalize_plan(once)["commands"] == once["commands"]


def test_send_plan_dry_run_sends_nothing():
    results = core.send_plan({"commands": [{"action": "play", "args": {}}]},
                             dry_run=True, verbose=False, delay=0)
    assert [r["ok"] for r in results] == [True]


def test_send_plan_without_bridge_reports_failure(unused_udp_port):
    core.UDP_PORT = unused_udp_port
    results = core.send_plan({"commands": [{"action": "play", "args": {}},
                                           {"action": "stop", "args": {}}]},
                             verbose=False, delay=0, timeout=0.2)
    assert [r["ok"] for r in results] == [False, False]


def test_current_endpoint_is_a_string(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    endpoint = core.current_endpoint()
    assert endpoint == "http://localhost:11434/v1"
    json.dumps({"endpoint": endpoint})  # must be JSON serializable
