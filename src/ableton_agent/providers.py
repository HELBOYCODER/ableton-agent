# -*- coding: utf-8 -*-
"""Provider management and Localhost / Free model auto-discovery for ableton-agent."""

import json
import os
import re
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


ALIASES = {
    "local": "ollama",
    "offline": "ollama",
    "lm-studio": "lmstudio",
    "lm": "lmstudio",
    "router": "9router",
    "openrouter": "openrouter-free",
    "free": "openrouter-free",
    "google": "gemini",
    "jan.ai": "jan",
}


def resolve_provider_key(key):
    """Map user input ('ollama', 'LM Studio', 'openrouter') to a provider key."""
    key = (key or "").lower().strip()
    if key in PROVIDERS:
        return key
    if key in ALIASES:
        return ALIASES[key]
    prefix = [k for k in PROVIDERS if k.startswith(key)] if key else []
    if len(prefix) == 1:
        return prefix[0]
    compact = key.replace(" ", "").replace("-", "").replace(".", "")
    for k, val in PROVIDERS.items():
        if compact and compact in val["name"].lower().replace(" ", "").replace("-", "").replace(".", ""):
            return k
    return None


def switch_provider(key, custom_model=None):
    """Switch active provider and configure environment variables."""
    resolved = resolve_provider_key(key)
    p = PROVIDERS.get(resolved) if resolved else None
    key = resolved or key

    if not p:
        raise ValueError("Unknown provider: '%s'. Available: %s" % (key, ", ".join(PROVIDERS.keys())))

    os.environ["LLM_BASE_URL"] = p["endpoint"]
    chosen_model = custom_model or p["default_model"]
    os.environ["LLM_MODEL"] = chosen_model

    if p.get("default_key"):
        # Localhost doesn't need a real API key; a cloud key must not leak into
        # a local endpoint either, so overwrite whatever was set before.
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
PERSIAN_DIGITS = {
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
}

# Drum machine model numbers must never be mistaken for a tempo.
DRUM_MACHINES = ("808", "909", "707", "606", "303", "727", "101")

GENRES = [
    {
        "keys": ["tech house", "tech-house", "تک هاوس", "تک‌هاوس"],
        "name": "Tech House", "tempo": 126.0, "kick_vel": 114,
        "root": "E2", "chord": "min7", "bass": [40, 40, 43, 41],
        "swing": 0.12, "hats": (11, 16), "clap": True,
    },
    {
        "keys": ["techno", "تکنو"],
        "name": "Techno", "tempo": 132.0, "kick_vel": 118,
        "root": "D2", "chord": "min", "bass": [38, 38, 38, 41],
        "swing": 0.0, "hats": (8, 16), "clap": True,
    },
    {
        "keys": ["drum and bass", "drum & bass", "dnb", "d&b", "jungle", "دی ان بی"],
        "name": "Drum & Bass", "tempo": 174.0, "kick_vel": 116,
        "root": "F1", "chord": "min9", "bass": [29, 29, 34, 32],
        "swing": 0.0, "hats": (11, 16), "clap": True,
    },
    {
        "keys": ["trap", "drill", "تراپ"],
        "name": "Trap", "tempo": 142.0, "kick_vel": 120,
        "root": "G1", "chord": "min", "bass": [31, 31, 34, 36],
        "swing": 0.0, "hats": (13, 16), "clap": True,
    },
    {
        "keys": ["lo-fi", "lofi", "lo fi", "chill", "boom bap", "لوفای", "لو فای"],
        "name": "Lo-Fi Hip Hop", "tempo": 82.0, "kick_vel": 96,
        "root": "A2", "chord": "min9", "bass": [45, 48, 50, 47],
        "swing": 0.22, "hats": (7, 16), "clap": True,
    },
    {
        "keys": ["hip hop", "hiphop", "rap", "هیپ هاپ", "رپ"],
        "name": "Hip Hop", "tempo": 90.0, "kick_vel": 108,
        "root": "C2", "chord": "min7", "bass": [36, 36, 39, 41],
        "swing": 0.18, "hats": (9, 16), "clap": True,
    },
    {
        "keys": ["ambient", "drone", "cinematic", "امبینت", "پد", "محیطی"],
        "name": "Dark Ambient", "tempo": 65.0, "kick_vel": 80,
        "root": "F2", "chord": "min7", "bass": [33, 33, 35, 33],
        "swing": 0.0, "hats": (3, 16), "clap": False,
    },
    {
        "keys": ["afro", "amapiano", "آفرو", "آماپیانو"],
        "name": "Afro House", "tempo": 114.0, "kick_vel": 110,
        "root": "G2", "chord": "min7", "bass": [43, 43, 46, 45],
        "swing": 0.16, "hats": (9, 16), "clap": True,
    },
    {
        "keys": ["trance", "psy", "ترنس"],
        "name": "Trance", "tempo": 138.0, "kick_vel": 116,
        "root": "A1", "chord": "min", "bass": [33, 33, 33, 33],
        "swing": 0.0, "hats": (8, 16), "clap": False,
    },
    {
        "keys": ["deep house", "house", "هاوس", "دیپ هاوس"],
        "name": "Deep House", "tempo": 122.0, "kick_vel": 110,
        "root": "F2", "chord": "min9", "bass": [41, 41, 44, 43],
        "swing": 0.1, "hats": (8, 16), "clap": True,
    },
]

DEFAULT_GENRE = GENRES[0]


def normalize_digits(text):
    """Convert Persian/Arabic-Indic digits to ASCII so '۱۲۸' parses as 128."""
    return "".join(PERSIAN_DIGITS.get(ch, ch) for ch in text or "")


def detect_genre(prompt):
    p = normalize_digits(prompt).lower()
    for genre in GENRES:
        if any(k in p for k in genre["keys"]):
            return genre
    return DEFAULT_GENRE


def detect_tempo(prompt, default=126.0):
    """Extract a BPM from free text in English or Persian.

    Explicit '126 bpm' / 'تمپو ۱۲۶' wins; a bare number is only accepted when
    it is a plausible tempo and not a drum machine ('909 drums' is not 909 BPM).
    """
    p = normalize_digits(prompt).lower()
    explicit = re.search(
        r"(?:(\d{2,3})\s*(?:bpm|b\.p\.m|beats per minute|بی\s*پی\s*ام|ضرب))"
        r"|(?:(?:bpm|tempo|تمپو|سرعت)\s*[:=]?\s*(\d{2,3}))", p)
    if explicit:
        value = float(explicit.group(1) or explicit.group(2))
        if 40 <= value <= 300:
            return value
    for match in re.finditer(r"\d{2,3}", p):
        token = match.group(0)
        if token in DRUM_MACHINES:
            continue
        value = float(token)
        if 60 <= value <= 200:
            return value
    return default


# A MIDI track with no instrument is silent, so every generated track gets one.
# Each entry is a list of browser candidates tried in order by the bridge.
DRUM_KIT = ["Kit-Core 909", "Kit-Core 808", "909 Core Kit", "Drum Rack"]
BASS_INSTRUMENT = ["Bass", "Operator", "Analog", "Wavetable"]
KEYS_INSTRUMENT = ["Grand Piano", "Wavetable", "Operator", "Analog"]


def _instrument(track, candidates):
    return [{"action": "load_device",
             "args": {"track": track, "device_name": list(candidates)}}]


def _clip(track, notes, length=4.0, slot=0):
    return [
        {"action": "create_clip",
         "args": {"track": track, "slot": slot, "length_beats": length}},
        {"action": "add_notes",
         "args": {"track": track, "slot": slot, "notes": notes}},
    ]


def generate_heuristic_plan(prompt, humanize=True):
    """Rule-based music producer used when no LLM is reachable.

    Builds a four-to-five track Ableton arrangement offline. Tracks are
    addressed by name so the plan lands correctly in a set that already has
    tracks in it.
    """
    from . import theory

    genre = detect_genre(prompt)
    tempo = detect_tempo(prompt, default=genre["tempo"])
    kick_vel = genre["kick_vel"]

    def shape(notes, swing=0.0):
        return theory.humanize_notes(notes, swing=swing) if humanize else notes

    commands = [
        {"action": "set_tempo", "args": {"bpm": tempo}},
        {"action": "message",
         "args": {"text": "ableton-agent: building %s at %.0f BPM" % (genre["name"], tempo)}},
    ]

    # --- Kick -----------------------------------------------------------
    commands.append({"action": "create_midi_track", "args": {"name": "Kick"}})
    if genre["name"] in ("Trap", "Hip Hop", "Drum & Bass"):
        kick_hits = [0.0, 0.75, 2.5, 3.0]
    elif genre["name"] == "Dark Ambient":
        kick_hits = [0.0, 2.0]
    else:
        kick_hits = [0.0, 1.0, 2.0, 3.0]  # four-on-the-floor
    kick_notes = [
        {"pitch": 36, "start": s, "length": 0.25,
         "velocity": kick_vel if s % 2 == 0 else kick_vel - 6}
        for s in kick_hits
    ]
    commands += _instrument("Kick", DRUM_KIT)
    commands += _clip("Kick", shape(kick_notes))

    # --- Clap / snare ---------------------------------------------------
    if genre["clap"]:
        commands.append({"action": "create_midi_track", "args": {"name": "Clap"}})
        clap_notes = [
            {"pitch": 39, "start": 1.0, "length": 0.25, "velocity": 104},
            {"pitch": 39, "start": 3.0, "length": 0.25, "velocity": 108},
        ]
        commands += _instrument("Clap", DRUM_KIT)
        commands += _clip("Clap", shape(clap_notes))

    # --- Bass -----------------------------------------------------------
    commands.append({"action": "create_midi_track", "args": {"name": "Sub Bass"}})
    bass_notes = []
    for i, pitch in enumerate(genre["bass"]):
        bass_notes.append({"pitch": pitch, "start": i * 1.0 + 0.5, "length": 0.35, "velocity": 102})
        bass_notes.append({"pitch": pitch, "start": i * 1.0 + 0.75, "length": 0.2, "velocity": 84})
    commands += _instrument("Sub Bass", BASS_INSTRUMENT)
    commands += _clip("Sub Bass", shape(bass_notes, swing=genre["swing"]))

    # --- Chords ---------------------------------------------------------
    commands.append({"action": "create_midi_track", "args": {"name": "Chords"}})
    chord_pitches = theory.get_chord_notes(genre["root"], genre["chord"], octave=3)
    chord_notes = [
        {"pitch": p, "start": 0.0, "length": 3.75, "velocity": 88 + (i % 2) * 6}
        for i, p in enumerate(chord_pitches)
    ]
    commands += _instrument("Chords", KEYS_INSTRUMENT)
    commands += _clip("Chords", shape(chord_notes))

    # --- Hats (Euclidean) -----------------------------------------------
    commands.append({"action": "create_midi_track", "args": {"name": "Hi-Hats"}})
    hits, steps = genre["hats"]
    pattern = theory.euclidean_rhythm(hits, steps)
    step_len = 4.0 / steps
    hat_notes = []
    for i, hit in enumerate(pattern):
        if not hit:
            continue
        on_beat = (i * step_len) % 1.0 == 0
        hat_notes.append({
            "pitch": 46 if i % steps == steps // 2 else 42,
            "start": round(i * step_len, 4),
            "length": 0.12,
            "velocity": 88 if on_beat else 72,
        })
    commands += _instrument("Hi-Hats", DRUM_KIT)
    commands += _clip("Hi-Hats", shape(hat_notes, swing=genre["swing"]))

    # --- Mix & transport -------------------------------------------------
    mix = {"Kick": 0.88, "Clap": 0.74, "Sub Bass": 0.80, "Chords": 0.68, "Hi-Hats": 0.66}
    for name, value in mix.items():
        if name == "Clap" and not genre["clap"]:
            continue
        commands.append({"action": "set_volume", "args": {"track": name, "value": value}})
    commands.append({"action": "play", "args": {}})

    return {
        "commands": commands,
        "genre": genre["name"],
        "tempo": tempo,
        "heuristic": True,
    }
