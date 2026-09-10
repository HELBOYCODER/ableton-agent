# -*- coding: utf-8 -*-
"""Claude Code-style Interactive Terminal (REPL) for ableton-agent.

Provides a full-featured, colorful terminal environment for musicians and producers
to talk with an AI music agent and control Ableton Live 11/12 in real-time.
"""

import json
import os
import re
import readline
import shutil
import socket
import sys
import time

from . import __version__, core, theory
from .cli import cmd_install

# -----------------------------------------------------------------------------
# ANSI Styling & Colors
# -----------------------------------------------------------------------------
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright
    BR_BLACK = "\033[90m"
    BR_RED = "\033[91m"
    BR_GREEN = "\033[92m"
    BR_YELLOW = "\033[93m"
    BR_BLUE = "\033[94m"
    BR_MAGENTA = "\033[95m"
    BR_CYAN = "\033[96m"
    BR_WHITE = "\033[97m"


HISTORY_FILE = os.path.expanduser("~/.ableton_agent_history")

SLASH_COMMANDS = [
    "/help", "/status", "/connect", "/install", "/live", "/set",
    "/play", "/stop", "/tempo", "/track", "/chord", "/groove",
    "/model", "/endpoint", "/provider", "/providers", "/free",
    "/mcp", "/dry", "/clear", "/exit", "/quit",
]


def _completer(text, state):
    options = [cmd for cmd in SLASH_COMMANDS if cmd.startswith(text)]
    if state < len(options):
        return options[state]
    return None


def init_readline():
    try:
        readline.set_completer(_completer)
        readline.parse_and_bind("tab: complete")
        if os.path.exists(HISTORY_FILE):
            readline.read_history_file(HISTORY_FILE)
    except Exception:
        pass


def save_readline():
    try:
        readline.set_history_length(1000)
        readline.write_history_file(HISTORY_FILE)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Status & Diagnostics
# -----------------------------------------------------------------------------
def get_live_status():
    """Ping Ableton Live bridge over UDP and measure response latency."""
    t0 = time.time()
    resp = core.send_command("describe_set", {}, wait_response=True, timeout=0.6, verbose=False)
    dt = (time.time() - t0) * 1000.0
    if resp and resp.get("status") == "ok":
        return True, dt, resp.get("result")
    return False, 0.0, None


def is_script_installed():
    """Check if ChatGPTBridge is placed in User Remote Scripts."""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Library", "Preferences", "Ableton"),
        os.path.join(os.environ.get("APPDATA", home), "Ableton"),
    ]
    for base in candidates:
        if os.path.isdir(base):
            for d in os.listdir(base):
                target = os.path.join(base, d, "User Remote Scripts", "ChatGPTBridge")
                if os.path.isdir(target):
                    return True, d
    return False, None


# -----------------------------------------------------------------------------
# Visual Banners & Formatting
# -----------------------------------------------------------------------------
def print_banner(live_connected=False, latency_ms=0.0):
    model = core.current_model()
    endpoint = os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1"
    host_port = "%s:%d" % (core.UDP_HOST, core.UDP_PORT)

    if live_connected:
        status_badge = "%s● LIVE CONNECTED (%dms)%s" % (C.BR_GREEN, int(latency_ms), C.RESET)
    else:
        status_badge = "%s○ LIVE OFFLINE%s" % (C.BR_YELLOW, C.RESET)

    print()
    print("  " + C.BR_CYAN + "╭─────────────────────────────────────────────────────────────╮" + C.RESET)
    print("  " + C.BR_CYAN + "│" + C.RESET + "  " + C.BOLD + C.BR_WHITE + "● ableton-agent" + C.RESET + " " + C.BR_CYAN + "v" + __version__ + C.RESET + "                        " + status_badge + " " + C.BR_CYAN + "│" + C.RESET)
    print("  " + C.BR_CYAN + "│" + C.RESET + "  " + C.DIM + "Claude Code-style AI Music Production Terminal" + C.RESET + "             " + C.BR_CYAN + "│" + C.RESET)
    print("  " + C.BR_CYAN + "│" + C.RESET + "                                                             " + C.BR_CYAN + "│" + C.RESET)
    print("  " + C.BR_CYAN + "│" + C.RESET + "  " + C.BOLD + "Model:" + C.RESET + " " + C.BR_MAGENTA + model.ljust(15) + C.RESET + " " + C.BOLD + "Bridge:" + C.RESET + " " + C.BR_WHITE + host_port.ljust(18) + C.RESET + " " + C.BR_CYAN + "│" + C.RESET)
    print("  " + C.BR_CYAN + "│" + C.RESET + "  " + C.BOLD + "API:" + C.RESET + "   " + C.DIM + endpoint[:44].ljust(44) + C.RESET + "       " + C.BR_CYAN + "│" + C.RESET)
    print("  " + C.BR_CYAN + "│" + C.RESET + "                                                             " + C.BR_CYAN + "│" + C.RESET)
    print("  " + C.BR_CYAN + "│" + C.RESET + "  Type " + C.BR_YELLOW + "/help" + C.RESET + " for slash commands, or talk in natural language. " + C.BR_CYAN + "│" + C.RESET)
    print("  " + C.BR_CYAN + "╰─────────────────────────────────────────────────────────────╯" + C.RESET)
    print()


def print_help():
    print(C.BOLD + C.BR_WHITE + "\nCommand Reference (Claude Code style):" + C.RESET)
    cmds = [
        ("/help", "Show this help message"),
        ("/status", "Show connection diagnostics, models, and bridge info"),
        ("/connect", "Test latency and ping Ableton Live bridge"),
        ("/install", "1-click auto-install ChatGPTBridge into Ableton"),
        ("/live, /set", "Inspect active project tracks, tempo, devices & clips"),
        ("/play", "Start Ableton Live transport playback"),
        ("/stop", "Stop Ableton Live transport playback"),
        ("/tempo <bpm>", "Set project tempo (e.g. /tempo 126)"),
        ("/track <midi|audio> [name]", "Quick create a new track in Live"),
        ("/chord <root> [type]", "Generate chord (e.g. /chord C3 min7, G2 min9)"),
        ("/groove [hits] [steps]", "Generate Euclidean polyrhythm (e.g. /groove 5 16)"),
        ("/provider [name]", "Switch provider (ollama, lmstudio, 9router, openrouter-free)"),
        ("/model [name]", "Show or switch active LLM (gpt-4o, qwen2.5:14b...)"),
        ("/endpoint [url]", "Show or set LLM API endpoint"),
        ("/mcp", "Display MCP server configuration for Claude Desktop / Cursor"),
        ("/dry", "Toggle dry-run mode (preview plan without touching Live)"),
        ("/clear", "Clear terminal screen"),
        ("/exit, /quit", "Exit the interactive session"),
    ]
    for name, desc in cmds:
        print("  " + C.BR_CYAN + name.ljust(26) + C.RESET + C.DIM + desc + C.RESET)

    print(C.BOLD + C.BR_WHITE + "\nNatural Language Examples:" + C.RESET)
    examples = [
        "make a tech house groove at 126 BPM with 909 kick, clap, and rolling bass",
        "create a lo-fi hip hop beat at 82 BPM with jazzy rhodes chords",
        "build a dark ambient pad with slow filter sweep and reverb",
        "what tracks and devices do I have currently?",
        "mute the bass track and turn down the reverb return bus",
        "یه ریتم هاوس ۱۲۶ بساز با بیس و کیک و های‌هت",
    ]
    for ex in examples:
        print("  " + C.BR_YELLOW + "❯ " + C.RESET + C.ITALIC + ex + C.RESET)
    print()


def print_status():
    from . import providers
    connected, latency, set_info = get_live_status()
    installed, detected = is_script_installed()
    local_engines = providers.detect_local_providers()

    print(C.BOLD + C.BR_WHITE + "\nAbleton Agent System Status:" + C.RESET)
    print("  Version      : " + C.BR_CYAN + "v" + __version__ + C.RESET)
    print("  Active Model : " + C.BR_MAGENTA + core.current_model() + C.RESET)
    print("  API Endpoint : " + C.DIM + (os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1") + C.RESET)
    print("  API Key      : " + (C.BR_GREEN + "Set" + C.RESET if os.environ.get("OPENAI_API_KEY") else C.BR_YELLOW + "NOT set (Localhost / Offline mode)" + C.RESET))
    print("  UDP Bridge   : " + C.BR_WHITE + "%s:%d" % (core.UDP_HOST, core.UDP_PORT) + C.RESET)

    if local_engines:
        names = ", ".join(["%s (port %d)" % (e["name"], e["port"]) for e in local_engines])
        print("  Local Engines: " + C.BR_GREEN + names + C.RESET)
    else:
        print("  Local Engines: " + C.DIM + "None detected on localhost (start Ollama or LM Studio)" + C.RESET)

    if connected:
        print("  Ableton Live : " + C.BR_GREEN + "CONNECTED" + C.RESET + C.DIM + " (latency: %.1fms)" % latency + C.RESET)
        if set_info:
            print("  Project State: " + C.BR_WHITE + "%.1f BPM, %d tracks" % (set_info.get("tempo", 120), len(set_info.get("tracks", []))) + C.RESET)
    elif installed:
        print("  Ableton Live : " + C.BR_YELLOW + "Script Installed (" + str(detected) + "), Waiting for Live connection..." + C.RESET)
        print("                 " + C.DIM + "In Ableton: Preferences > Link/MIDI > Control Surface = ChatGPTBridge" + C.RESET)
    else:
        print("  Ableton Live : " + C.BR_RED + "Script NOT installed" + C.RESET + C.DIM + " (run /install to setup)" + C.RESET)
    print()


def print_live_set():
    connected, _, set_info = get_live_status()
    if not connected or not set_info:
        print(C.BR_YELLOW + "\n[!] Could not query Ableton Live. Is Ableton running with ChatGPTBridge active?" + C.RESET)
        print(C.DIM + "    Run /install or restart Ableton > Preferences > Control Surface = ChatGPTBridge.\n" + C.RESET)
        return

    tempo = set_info.get("tempo", 120.0)
    tracks = set_info.get("tracks", [])
    returns = set_info.get("return_tracks", [])

    print(C.BOLD + C.BR_WHITE + "\nLive Project State:" + C.RESET + " " + C.BR_CYAN + "%.1f BPM" % tempo + C.RESET + " • " + C.BR_MAGENTA + "%d Tracks" % len(tracks) + C.RESET)
    print(C.DIM + "─" * 68 + C.RESET)
    print(C.BOLD + " #   Type    Name                  Devices / Instruments" + C.RESET)
    print(C.DIM + "─" * 68 + C.RESET)

    if not tracks:
        print("  " + C.DIM + "(No tracks in current set)" + C.RESET)

    for t in tracks:
        idx = str(t.get("index", 0) + 1).rjust(2)
        ttype = (C.BR_BLUE + "MIDI " + C.RESET) if t.get("is_midi") else (C.BR_GREEN + "AUDIO" + C.RESET)
        name = (t.get("name") or "Track").ljust(21)[:21]
        devs = ", ".join(t.get("devices", [])) or "(None)"
        print(" %s  %s  %s %s" % (idx, ttype, name, C.DIM + devs[:32] + C.RESET))

    if returns:
        print(C.DIM + "─" * 68 + C.RESET)
        print(" " + C.BOLD + "Return Tracks:" + C.RESET + " " + C.DIM + ", ".join(returns) + C.RESET)
    print()


# -----------------------------------------------------------------------------
# Agentic Execution Loop
# -----------------------------------------------------------------------------
def execute_plan(plan, dry_run=False):
    commands = plan.get("commands", [])
    if not commands:
        print(C.BR_YELLOW + "● No commands generated." + C.RESET)
        return

    print(C.BOLD + C.BR_WHITE + "\n● Executing in Ableton Live (%d commands):" % len(commands) + C.RESET)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)

    for i, cmd in enumerate(commands):
        is_last = (i == len(commands) - 1)
        prefix = "  └── " if is_last else "  ├── "
        action = cmd.get("action", "")
        args = cmd.get("args", {}) or {}
        args_summary = json.dumps(args, ensure_ascii=False)
        if len(args_summary) > 42:
            args_summary = args_summary[:39] + "..."

        step_str = "[%d/%d] %s(%s)" % (i + 1, len(commands), action, args_summary)
        sys.stdout.write(prefix + C.BR_WHITE + step_str.ljust(50) + C.RESET)
        sys.stdout.flush()

        if dry_run:
            print(C.BR_YELLOW + "○ DRY-RUN" + C.RESET)
            continue

        try:
            sock.sendto(json.dumps(cmd).encode("utf-8"), (core.UDP_HOST, core.UDP_PORT))
            # Brief pause to let Live process
            time.sleep(0.08)
            print(C.BR_GREEN + "✔ OK" + C.RESET)
        except Exception as e:
            print(C.BR_RED + "✖ ERR (%s)" % e + C.RESET)

    sock.close()
    if not dry_run:
        print(C.BOLD + C.BR_GREEN + "✔ Done! Check Ableton Live." + C.RESET + "\n")
    else:
        print(C.BOLD + C.BR_YELLOW + "✔ Dry run complete (no commands sent)." + C.RESET + "\n")


def handle_natural_language(user_prompt, dry_run=False):
    # Check if user is asking about current set state
    lowered = user_prompt.lower()
    asking_set = any(k in lowered for k in ["what track", "describe", "current set", "list track", "inspect", "چه ترک", "ترک‌ها"])
    if asking_set:
        print_live_set()
        return

    print("  " + C.BR_CYAN + "● Thinking with " + core.current_model() + "..." + C.RESET, end="\r", flush=True)

    try:
        plan = core.get_plan(user_prompt, verbose=False)
        # Clear thinking line
        sys.stdout.write(" " * 60 + "\r")
        sys.stdout.flush()
        execute_plan(plan, dry_run=dry_run)
    except Exception as e:
        sys.stdout.write(" " * 60 + "\r")
        sys.stdout.flush()
        print(C.BR_RED + "● Error planning track: " + str(e) + C.RESET)
        if "api_key" in str(e).lower() or not os.environ.get("OPENAI_API_KEY"):
            print(C.DIM + "  Tip: Set your key with `export OPENAI_API_KEY=\"...\"` or switch to local Ollama with `/model qwen2.5:14b`\n" + C.RESET)


# -----------------------------------------------------------------------------
# Main Terminal Interactive REPL
# -----------------------------------------------------------------------------
def run_terminal():
    init_readline()
    dry_run = False

    connected, latency, _ = get_live_status()
    print_banner(connected, latency)

    try:
        while True:
            prompt_str = C.BOLD + C.BR_CYAN + "ableton-agent" + C.RESET
            if dry_run:
                prompt_str += C.BR_YELLOW + " (dry)" + C.RESET
            prompt_str += C.BOLD + C.BR_WHITE + " ❯ " + C.RESET

            try:
                line = input(prompt_str).strip()
            except (EOFError, KeyboardInterrupt):
                print(C.DIM + "\nGoodbye! 🎹" + C.RESET)
                break

            if not line:
                continue

            # Check slash commands
            parts = line.split()
            cmd = parts[0].lower()

            if cmd in ("/exit", "/quit", "exit", "quit"):
                print(C.DIM + "Goodbye! 🎹" + C.RESET)
                break

            elif cmd in ("/help", "help", "?"):
                print_help()

            elif cmd in ("/status", "status"):
                print_status()

            elif cmd == "/connect":
                conn, lat, _ = get_live_status()
                if conn:
                    print(C.BR_GREEN + "✔ Connected to Ableton Live ChatGPTBridge! Latency: %.1fms" % lat + C.RESET)
                else:
                    print(C.BR_RED + "✖ Could not connect to UDP port %d. Is Ableton Live open?" % core.UDP_PORT + C.RESET)

            elif cmd == "/install":
                class DummyArgs:
                    dest = None
                print(C.BR_CYAN + "Installing ChatGPTBridge into Ableton..." + C.RESET)
                cmd_install(DummyArgs())

            elif cmd in ("/live", "/set"):
                print_live_set()

            elif cmd == "/play":
                core.send_command("play", verbose=False)
                print(C.BR_GREEN + "▶ Playback started." + C.RESET)

            elif cmd == "/stop":
                core.send_command("stop", verbose=False)
                print(C.BR_YELLOW + "■ Playback stopped." + C.RESET)

            elif cmd == "/tempo":
                if len(parts) > 1:
                    try:
                        bpm = float(parts[1])
                        core.send_command("set_tempo", {"bpm": bpm}, verbose=False)
                        print(C.BR_GREEN + "✔ Tempo set to %.1f BPM" % bpm + C.RESET)
                    except ValueError:
                        print(C.BR_RED + "Usage: /tempo <number>, e.g. /tempo 126" + C.RESET)
                else:
                    print(C.BR_RED + "Usage: /tempo <bpm>" + C.RESET)

            elif cmd == "/track":
                if len(parts) > 1:
                    ttype = parts[1].lower()
                    name = " ".join(parts[2:]) if len(parts) > 2 else "Track"
                    if ttype in ("midi", "mid"):
                        core.send_command("create_midi_track", {"name": name}, verbose=False)
                        print(C.BR_GREEN + "✔ Created MIDI track: '%s'" % name + C.RESET)
                    elif ttype in ("audio", "aud"):
                        core.send_command("create_audio_track", {"name": name}, verbose=False)
                        print(C.BR_GREEN + "✔ Created Audio track: '%s'" % name + C.RESET)
                    else:
                        print(C.BR_RED + "Usage: /track <midi|audio> [name]" + C.RESET)
                else:
                    print(C.BR_RED + "Usage: /track <midi|audio> [name]" + C.RESET)

            elif cmd == "/chord":
                root = parts[1] if len(parts) > 1 else "C3"
                ctype = parts[2] if len(parts) > 2 else "min7"
                pitches = theory.get_chord_notes(root, ctype)
                print(C.BR_CYAN + "Chord %s %s -> MIDI pitches: %s" % (root, ctype, pitches) + C.RESET)
                notes = [{"pitch": p, "start": 0.0, "length": 2.0, "velocity": 100} for p in pitches]
                core.send_command("create_clip", {"track_index": 0, "slot": 0, "length_beats": 4.0}, verbose=False)
                core.send_command("add_notes", {"track_index": 0, "slot": 0, "notes": notes}, verbose=False)
                print(C.BR_GREEN + "✔ Sent chord to Track 1, Clip 1" + C.RESET)

            elif cmd == "/groove":
                hits = int(parts[1]) if len(parts) > 1 else 5
                steps = int(parts[2]) if len(parts) > 2 else 16
                pattern = theory.euclidean_rhythm(hits, steps)
                print(C.BR_CYAN + "Euclidean Rhythm (%d/%d): %s" % (hits, steps, pattern) + C.RESET)
                step_len = 4.0 / steps
                notes = []
                for i, h in enumerate(pattern):
                    if h:
                        notes.append({"pitch": 36, "start": round(i * step_len, 4), "length": 0.2, "velocity": 105})
                core.send_command("create_clip", {"track_index": 0, "slot": 1, "length_beats": 4.0}, verbose=False)
                core.send_command("add_notes", {"track_index": 0, "slot": 1, "notes": notes}, verbose=False)
                print(C.BR_GREEN + "✔ Sent Euclidean beat to Track 1, Clip 2" + C.RESET)

            elif cmd == "/model":
                if len(parts) > 1:
                    new_model = parts[1]
                    os.environ["LLM_MODEL"] = new_model
                    print(C.BR_GREEN + "✔ Active model changed to: " + new_model + C.RESET)
                else:
                    print(C.BR_MAGENTA + "Current model: " + core.current_model() + C.RESET)
                    print(C.DIM + "Common models: gpt-4o, qwen2.5:14b, llama-3.3-70b-versatile, deepseek-chat" + C.RESET)

            elif cmd == "/endpoint":
                if len(parts) > 1:
                    new_ep = parts[1]
                    os.environ["LLM_BASE_URL"] = new_ep
                    print(C.BR_GREEN + "✔ Active API endpoint: " + new_ep + C.RESET)
                else:
                    print(C.BR_CYAN + "Current API endpoint: " + (os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1") + C.RESET)

            elif cmd in ("/provider", "/providers", "/free"):
                from . import providers
                if len(parts) > 1:
                    prov_key = parts[1]
                    cust_model = parts[2] if len(parts) > 2 else None
                    try:
                        info = providers.switch_provider(prov_key, cust_model)
                        print(C.BR_GREEN + "✔ Switched to provider: " + info["name"] + C.RESET)
                        print("  Model    : " + C.BR_MAGENTA + info["model"] + C.RESET)
                        print("  Endpoint : " + C.DIM + info["endpoint"] + C.RESET)
                    except ValueError as ve:
                        print(C.BR_RED + str(ve) + C.RESET)
                else:
                    print(C.BOLD + C.BR_WHITE + "\nSupported Localhost & Free Providers:" + C.RESET)
                    for k, p in providers.PROVIDERS.items():
                        local_tag = C.BR_GREEN + "[LOCAL]" + C.RESET if p["is_local"] else C.BR_CYAN + "[CLOUD]" + C.RESET
                        print("  " + local_tag + " " + C.BOLD + k.ljust(16) + C.RESET + C.DIM + p["name"] + C.RESET)
                        print("          Endpoint : " + C.DIM + p["endpoint"] + C.RESET)
                        print("          Models   : " + C.BR_MAGENTA + ", ".join(p["models"][:4]) + C.RESET)

                    # Check for live local engines
                    detected = providers.detect_local_providers()
                    print(C.BOLD + C.BR_WHITE + "\nDetected Live on Your Machine:" + C.RESET)
                    if detected:
                        for d in detected:
                            print("  " + C.BR_GREEN + "● " + d["name"] + C.RESET + " (port " + str(d["port"]) + ")")
                            if d.get("models"):
                                print("    Available models: " + C.BR_CYAN + ", ".join(d["models"][:6]) + C.RESET)
                    else:
                        print("  " + C.DIM + "No localhost AI engines currently detected (start Ollama or LM Studio)." + C.RESET)

                    print(C.BOLD + C.BR_WHITE + "\nUsage:" + C.RESET)
                    print("  /provider ollama              (use local Ollama)")
                    print("  /provider 9router             (use 9Router free models on port 20128)")
                    print("  /provider openrouter-free     (use OpenRouter free 70B models)")
                    print("  /provider lmstudio            (use LM Studio on port 1234)\n")

            elif cmd == "/mcp":
                cfg = {
                    "mcpServers": {
                        "ableton-agent": {
                            "command": "ableton-agent",
                            "args": ["mcp"]
                        }
                    }
                }
                print(C.BOLD + C.BR_WHITE + "\nAdd to claude_desktop_config.json or Cursor MCP settings:" + C.RESET)
                print(C.BR_CYAN + json.dumps(cfg, indent=2) + C.RESET + "\n")

            elif cmd == "/dry":
                dry_run = not dry_run
                status_str = "ENABLED (commands will not touch Live)" if dry_run else "DISABLED (live execution)"
                print(C.BR_YELLOW + "● Dry-run mode: " + status_str + C.RESET)

            elif cmd in ("/clear", "clear"):
                os.system("clear" if os.name != "nt" else "cls")
                connected, latency, _ = get_live_status()
                print_banner(connected, latency)

            else:
                # Natural Language Prompt!
                handle_natural_language(line, dry_run=dry_run)

    finally:
        save_readline()
