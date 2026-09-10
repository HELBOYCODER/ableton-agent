# -*- coding: utf-8 -*-
"""Provider management and Localhost / Free model auto-discovery for ableton-agent."""

import json
import os
import socket
import urllib.request
import urllib.error

# Predefined provider presets (Localhost & Free Cloud)
PROVIDERS = {
    "ollama": {
        "name": "Ollama (100% Local & Free)",
        "endpoint": "http://localhost:11434/v1",
        "default_model": "qwen2.5:14b",
        "models": ["qwen2.5:14b", "qwen2.5:7b", "llama3.1:8b", "deepseek-r1:14b", "mistral:7b"],
        "default_key": "ollama",
        "port": 11434,
        "is_local": True,
        "description": "Runs fully offline on your own machine. Zero API key needed.",
    },
    "lmstudio": {
        "name": "LM Studio (Localhost)",
        "endpoint": "http://localhost:1234/v1",
        "default_model": "local-model",
        "models": ["local-model"],
        "default_key": "lm-studio",
        "port": 1234,
        "is_local": True,
        "description": "Visual local LLM runner on port 1234. No API key needed.",
    },
    "9router": {
        "name": "9Router Local Gateway (Free Models)",
        "endpoint": "http://localhost:20128/v1",
        "default_model": "oc/mimo-v2.5-free",
        "models": ["oc/mimo-v2.5-free", "oc/ling-3.0-flash-fin-free", "gemini-2.0-flash"],
        "default_key": "9router",
        "port": 20128,
        "is_local": True,
        "description": "Local AI gateway proxying free models on port 20128.",
    },
    "openrouter-free": {
        "name": "OpenRouter (Free Cloud Models)",
        "endpoint": "https://openrouter.ai/api/v1",
        "default_model": "google/gemini-2.0-flash-exp:free",
        "models": [
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-r1:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "mistralai/mistral-small-24b-instruct-2501:free",
        ],
        "default_key": None,
        "port": None,
        "is_local": False,
        "description": "Access world-class 70B+ models completely free via OpenRouter.",
    },
    "groq": {
        "name": "Groq Cloud (Ultra-Fast Free Tier)",
        "endpoint": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "default_key": None,
        "port": None,
        "is_local": False,
        "description": "Sub-second inference speed with free tier API key.",
    },
    "gemini": {
        "name": "Google Gemini (Free Tier)",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "models": ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
        "default_key": None,
        "port": None,
        "is_local": False,
        "description": "Google's high-speed multimodal model with free monthly quota.",
    },
    "localai": {
        "name": "LocalAI (Localhost)",
        "endpoint": "http://localhost:8080/v1",
        "default_model": "gpt-4",
        "models": ["gpt-4"],
        "default_key": "not-needed",
        "port": 8080,
        "is_local": True,
        "description": "Self-hosted OpenAI replacement on port 8080.",
    },
    "jan": {
        "name": "Jan.ai (Localhost)",
        "endpoint": "http://localhost:1337/v1",
        "default_model": "mistral-ins-7b-q4",
        "models": ["mistral-ins-7b-q4"],
        "default_key": "jan",
        "port": 1337,
        "is_local": True,
        "description": "Local desktop runner on port 1337.",
    },
    "openai": {
        "name": "OpenAI Official",
        "endpoint": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
        "default_key": None,
        "port": None,
        "is_local": False,
        "description": "Default standard provider.",
    },
}


def check_port(host, port, timeout=0.15):
    """Fast non-blocking port check."""
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def get_ollama_models():
    """Fetch installed local models from Ollama API tags endpoint."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "ableton-agent"})
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            return models if models else None
    except Exception:
        return None


def detect_local_providers():
    """Scan localhost for running AI engines and return detected list."""
    detected = []
    for key, p in PROVIDERS.items():
        if p.get("is_local") and p.get("port"):
            if check_port("127.0.0.1", p["port"]):
                item = dict(p)
                item["key"] = key
                if key == "ollama":
                    installed = get_ollama_models()
                    if installed:
                        item["models"] = installed
                        item["default_model"] = installed[0]
                detected.append(item)
    return detected


def switch_provider(key, custom_model=None):
    """Switch active provider and configure environment variables."""
    key = key.lower().strip()
    p = PROVIDERS.get(key)
    if not p:
        # Check alias
        for k, val in PROVIDERS.items():
            if key in k or key in val["name"].lower():
                p = val
                key = k
                break

    if not p:
        raise ValueError("Unknown provider: '%s'. Available: %s" % (key, ", ".join(PROVIDERS.keys())))

    os.environ["LLM_BASE_URL"] = p["endpoint"]
    chosen_model = custom_model or p["default_model"]
    os.environ["LLM_MODEL"] = chosen_model

    if p.get("default_key"):
        # Localhost doesn't need real API key
        if not os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") == "not-needed":
            os.environ["OPENAI_API_KEY"] = p["default_key"]

    return {
        "key": key,
        "name": p["name"],
        "endpoint": p["endpoint"],
        "model": chosen_model,
        "is_local": p["is_local"],
    }


# -----------------------------------------------------------------------------
# Offline Rule-Based Heuristic Music Producer (0 API Key / 0 Tokens Fallback)
# -----------------------------------------------------------------------------
def generate_heuristic_plan(prompt):
    """
    Intelligent rule-based music producer.
    Builds professional Ableton Live tracks from keywords completely offline
    when no LLM API key is present or when offline mode is selected.
    """
    p = prompt.lower()
    commands = []

    # Detect genre & defaults
    if any(k in p for k in ["techno", "تکنو"]):
        tempo = 130.0
        genre = "Techno"
        kick_vel = 118
        bass_notes = [36, 36, 38, 36]
        chord_root = "D2"
        chord_type = "min"
    elif any(k in p for k in ["lo-fi", "lofi", "chill", "لورفای", "لوفای"]):
        tempo = 82.0
        genre = "Lo-Fi Hip Hop"
        kick_vel = 96
        bass_notes = [45, 48, 50, 47]
        chord_root = "A2"
        chord_type = "min9"
    elif any(k in p for k in ["ambient", "dark", "drone", "امبینت", "پد"]):
        tempo = 65.0
        genre = "Dark Ambient"
        kick_vel = 80
        bass_notes = [33, 33, 35, 33]
        chord_root = "F2"
        chord_type = "min7"
    elif any(k in p for k in ["afro", "amapiano", "آفرو"]):
        tempo = 114.0
        genre = "Afrobeat"
        kick_vel = 110
        bass_notes = [43, 43, 46, 45]
        chord_root = "G2"
        chord_type = "min7"
    else:
        # Default: Tech House
        tempo = 126.0
        genre = "Tech House"
        kick_vel = 114
        bass_notes = [40, 40, 43, 41]
        chord_root = "E2"
        chord_type = "min7"

    # Extract user-specified BPM if present
    import re
    bpm_match = re.search(r"(\d{2,3})\s*(?:bpm|تمپو)?", p)
    if bpm_match:
        val = float(bpm_match.group(1))
        if 50 <= val <= 200:
            tempo = val

    # 1. Set Tempo
    commands.append({"action": "set_tempo", "args": {"bpm": tempo}})
    commands.append({"action": "message", "args": {"text": "Building %s track at %.0f BPM..." % (genre, tempo)}})

    # 2. Track 1: Kick Drum
    commands.append({"action": "create_midi_track", "args": {"name": "Kick 909"}})
    commands.append({"action": "create_clip", "args": {"track_index": 0, "slot": 0, "length_beats": 4.0}})
    kick_notes = [
        {"pitch": 36, "start": 0.0, "length": 0.25, "velocity": kick_vel},
        {"pitch": 36, "start": 1.0, "length": 0.25, "velocity": kick_vel - 4},
        {"pitch": 36, "start": 2.0, "length": 0.25, "velocity": kick_vel},
        {"pitch": 36, "start": 3.0, "length": 0.25, "velocity": kick_vel - 4},
    ]
    commands.append({"action": "add_notes", "args": {"track_index": 0, "slot": 0, "notes": kick_notes}})

    # 3. Track 2: Rolling Bass
    commands.append({"action": "create_midi_track", "args": {"name": "Sub Bass"}})
    commands.append({"action": "create_clip", "args": {"track_index": 1, "slot": 0, "length_beats": 4.0}})
    from . import theory
    bass_clip_notes = []
    for i, pitch in enumerate(bass_notes):
        # 16th note rolling pattern
        bass_clip_notes.append({"pitch": pitch, "start": i * 1.0 + 0.5, "length": 0.35, "velocity": 102})
        bass_clip_notes.append({"pitch": pitch, "start": i * 1.0 + 0.75, "length": 0.2, "velocity": 88})
    commands.append({"action": "add_notes", "args": {"track_index": 1, "slot": 0, "notes": bass_clip_notes}})

    # 4. Track 3: Chords / Synths
    commands.append({"action": "create_midi_track", "args": {"name": "Chords Pad"}})
    commands.append({"action": "create_clip", "args": {"track_index": 2, "slot": 0, "length_beats": 4.0}})
    chord_pitches = theory.get_chord_notes(chord_root, chord_type, octave=3)
    chord_notes = [{"pitch": cp, "start": 0.0, "length": 3.8, "velocity": 92} for cp in chord_pitches]
    commands.append({"action": "add_notes", "args": {"track_index": 2, "slot": 0, "notes": chord_notes}})

    # 5. Track 4: Percussion / Hi-Hats
    commands.append({"action": "create_midi_track", "args": {"name": "Hi-Hats"}})
    commands.append({"action": "create_clip", "args": {"track_index": 3, "slot": 0, "length_beats": 4.0}})
    hat_notes = [
        {"pitch": 42, "start": 0.5, "length": 0.15, "velocity": 95},
        {"pitch": 42, "start": 1.5, "length": 0.15, "velocity": 98},
        {"pitch": 42, "start": 2.5, "length": 0.15, "velocity": 95},
        {"pitch": 42, "start": 3.5, "length": 0.15, "velocity": 104},
    ]
    commands.append({"action": "add_notes", "args": {"track_index": 3, "slot": 0, "notes": hat_notes}})

    # 6. Mixer Levels
    commands.append({"action": "set_volume", "args": {"track_index": 0, "value": 0.95}})
    commands.append({"action": "set_volume", "args": {"track_index": 1, "value": 0.88}})
    commands.append({"action": "set_volume", "args": {"track_index": 2, "value": 0.78}})
    commands.append({"action": "set_volume", "args": {"track_index": 3, "value": 0.82}})

    # 7. Start Transport
    commands.append({"action": "play", "args": {}})

    return {"commands": commands, "genre": genre, "tempo": tempo, "heuristic": True}
