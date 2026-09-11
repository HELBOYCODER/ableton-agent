# -*- coding: utf-8 -*-
import os

import pytest

from ableton_agent import providers


@pytest.mark.parametrize("alias,expected", [
    ("ollama", "ollama"),
    ("local", "ollama"),
    ("lm-studio", "lmstudio"),
    ("LM", "lmstudio"),
    ("router", "9router"),
    ("free", "openrouter-free"),
    ("google", "gemini"),
    ("jan.ai", "jan"),
])
def test_resolve_provider_aliases(alias, expected):
    assert providers.resolve_provider_key(alias) == expected


def test_resolve_unknown_provider():
    assert providers.resolve_provider_key("not-a-provider") is None
    with pytest.raises(ValueError):
        providers.switch_provider("not-a-provider")


def test_switch_to_local_provider_overwrites_cloud_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-cloud-key")
    info = providers.switch_provider("ollama")
    assert info["endpoint"] == "http://localhost:11434/v1"
    assert os.environ["OPENAI_API_KEY"] == "ollama"
    assert os.environ["LLM_BASE_URL"] == "http://localhost:11434/v1"


@pytest.mark.parametrize("prompt,expected", [
    ("tech house at 126 bpm", 126.0),
    ("make a beat at 90BPM", 90.0),
    (u"لوفای با ۹۰ بی پی ام", 90.0),
    (u"یه ریتم هاوس ۱۲۸ بساز", 128.0),
    ("trap with 808 sub bass", 142.0),        # 808 is a drum machine, not a tempo
    ("909 techno", 132.0),
])
def test_detect_tempo(prompt, expected):
    genre = providers.detect_genre(prompt)
    assert providers.detect_tempo(prompt, default=genre["tempo"]) == expected


def test_normalize_digits():
    assert providers.normalize_digits(u"۱۲۸") == "128"
    assert providers.normalize_digits(u"١٢٨") == "128"


def test_heuristic_plan_uses_named_tracks_only():
    plan = providers.generate_heuristic_plan("lo-fi at 82 bpm")
    assert plan["heuristic"] is True
    for cmd in plan["commands"]:
        assert "track_index" not in cmd["args"], cmd


def test_heuristic_plan_loads_an_instrument_per_track():
    plan = providers.generate_heuristic_plan("techno at 132 bpm")
    created = [c["args"]["name"] for c in plan["commands"]
               if c["action"] == "create_midi_track"]
    instrumented = [c["args"]["track"] for c in plan["commands"]
                    if c["action"] == "load_device"]
    assert created and created == instrumented


def test_heuristic_plan_is_valid_for_the_bridge():
    from ableton_agent import core

    plan = providers.generate_heuristic_plan("dark ambient")
    normalized = core.normalize_plan(plan)
    assert "dropped" not in normalized
    assert len(normalized["commands"]) == len(plan["commands"])
