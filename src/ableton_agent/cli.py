# -*- coding: utf-8 -*-
"""ableton-agent CLI - opencode-style commands for AI-driven Ableton control."""

import argparse
import json
import os
import shutil
import sys

from . import __version__, core


def _print_config():
    print("endpoint : %s" % core.current_endpoint())
    print("model    : %s" % core.current_model())
    print("udp      : %s:%d" % (core.UDP_HOST, core.UDP_PORT))
    print("api key  : %s" % ("set" if os.environ.get("OPENAI_API_KEY") else "NOT set"))


def cmd_run(a):
    plan = core.get_plan(a.prompt)
    results = core.send_plan(plan, delay=a.delay, dry_run=a.dry_run)
    if not a.dry_run and results and not any(r["ok"] for r in results):
        sys.exit("no response from Ableton Live - run `ableton-agent doctor` to diagnose")


def cmd_chat(a):
    from .terminal import run_terminal
    run_terminal()


def cmd_send(a):
    args = json.loads(a.args) if a.args else {}
    core.send_command(a.action, args, dry_run=a.dry_run)


def cmd_install(a):
    """Copy the bundled ChatGPTBridge Remote Script into Ableton."""
    src = os.path.join(os.path.dirname(__file__), "remote_script", "ChatGPTBridge")
    if not os.path.isdir(src):
        sys.exit("bundled Remote Script not found - reinstall the package")
    if a.dest:
        dest = os.path.join(os.path.expanduser(a.dest), "ChatGPTBridge")
        shutil.copytree(src, dest, dirs_exist_ok=True)
        print("installed to %s" % dest)
        print("restart Ableton > Preferences > Link/Tempo/MIDI > Control Surface = ChatGPTBridge")
        return
    home = os.path.expanduser("~")
    candidates = [
        # macOS user scripts (no admin needed)
        os.path.join(home, "Library", "Preferences", "Ableton"),
        # Windows user scripts
        os.path.join(os.environ.get("APPDATA", home), "Ableton"),
    ]
    installed = False
    for base in candidates:
        if os.path.isdir(base):
            for live_dir in sorted(os.listdir(base)):
                target = os.path.join(base, live_dir, "User Remote Scripts")
                if os.path.isdir(target) or live_dir.startswith("Live"):
                    os.makedirs(target, exist_ok=True)
                    shutil.copytree(src, os.path.join(target, "ChatGPTBridge"),
                                    dirs_exist_ok=True)
                    print("installed to %s" % os.path.join(target, "ChatGPTBridge"))
                    installed = True
    if not installed:
        print("could not auto-detect Ableton. Re-run with:")
        print("  ableton-agent install --dest \"<path to MIDI Remote Scripts>\"")
        print('  e.g. --dest "C:\\ProgramData\\Ableton\\Live 12\\Resources\\MIDI Remote Scripts"')
    else:
        print("restart Ableton > Preferences > Link/Tempo/MIDI > Control Surface = ChatGPTBridge")


def cmd_config(a):
    _print_config()
    print("\nset env vars to switch providers, e.g.:")
    print('  export LLM_BASE_URL="http://localhost:11434/v1"   # Ollama (local, free)')
    print('  export LLM_MODEL="qwen2.5:14b"')
    print('  export OPENAI_API_KEY="ollama"')


def cmd_mcp(a):
    from .mcp import run_mcp_server
    run_mcp_server()


def cmd_describe(a):
    resp = core.send_command("describe_set", wait_response=True, timeout=a.timeout)
    if resp:
        print(json.dumps(resp, indent=2))
    else:
        print("describe_set command dispatched (check Ableton Log.txt or ensure ChatGPTBridge is active).")


def cmd_providers(a):
    from . import providers
    if a.set:
        info = providers.switch_provider(a.set, a.model)
        print("Switched to provider: %s" % info["name"])
        print("  Model    : %s" % info["model"])
        print("  Endpoint : %s" % info["endpoint"])
    else:
        print("\nSupported Localhost & Free Providers:")
        for k, p in providers.PROVIDERS.items():
            loc = "[LOCAL]" if p["is_local"] else "[CLOUD]"
            print("  %s %-16s %s" % (loc, k, p["name"]))
            print("          Endpoint : %s" % p["endpoint"])
            print("          Models   : %s" % ", ".join(p["models"][:4]))
        detected = providers.detect_local_providers()
        print("\nLive Local Engines on this machine:")
        if detected:
            for d in detected:
                print("  ● %s (port %d)" % (d["name"], d["port"]))
        else:
            print("  (None currently detected on localhost)")
        print("\nSwitch provider with: ableton-agent providers --set ollama\n")


def cmd_theory(a):
    from . import theory
    if a.type == "chord":
        pitches = theory.get_chord_notes(a.root, a.chord_type)
        print("chord %s %s -> MIDI pitches: %s" % (a.root, a.chord_type, pitches))
    elif a.type == "euclidean":
        pattern = theory.euclidean_rhythm(a.hits, a.steps)
        print("euclidean rhythm (%d hits / %d steps): %s" % (a.hits, a.steps, pattern))


def cmd_app(a):
    from .gui.server import start_server
    start_server(port=a.port, open_browser=not a.no_open)


def cmd_simulate(a):
    from .simulator import run_simulator
    run_simulator(port=a.port, verbose=not a.quiet)


def cmd_doctor(a):
    """Diagnose the whole chain: script installed -> Live reachable -> LLM."""
    from . import providers

    ok = True
    print("ableton-agent %s doctor" % __version__)
    print("")

    installed, live_dir = _find_installed_bridge()
    if installed:
        print("[ok]   Remote Script installed  : %s" % installed)
    else:
        ok = False
        print("[FAIL] Remote Script installed  : not found (run `ableton-agent install`)")

    ping = core.send_command("ping", {}, wait_response=True, timeout=a.timeout, verbose=False)
    if ping and ping.get("status") == "ok":
        result = ping.get("result") or {}
        print("[ok]   Live bridge udp://%s:%d : bridge v%s, %.1f BPM, %s tracks"
              % (core.UDP_HOST, core.UDP_PORT, result.get("bridge_version", "?"),
                 result.get("tempo", 0.0), result.get("tracks", "?")))
    else:
        ok = False
        print("[FAIL] Live bridge udp://%s:%d : no reply" % (core.UDP_HOST, core.UDP_PORT))
        if installed and live_dir:
            print("       In Live: Preferences > Link/Tempo/MIDI > Control Surface = ChatGPTBridge")
        print("       No Ableton here? Run `ableton-agent simulate` in another shell.")

    detected = providers.detect_local_providers()
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_BASE_URL"):
        print("[ok]   LLM                      : %s (%s)" % (core.current_model(), core.current_endpoint()))
    elif detected:
        print("[ok]   LLM                      : local %s detected on port %d"
              % (detected[0]["name"], detected[0]["port"]))
    else:
        print("[warn] LLM                      : none configured - offline producer will be used")

    print("")
    print("overall: %s" % ("ready" if ok else "not ready"))
    if not ok:
        sys.exit(1)


def _find_installed_bridge():
    home = os.path.expanduser("~")
    for base in (os.path.join(home, "Library", "Preferences", "Ableton"),
                 os.path.join(os.environ.get("APPDATA", home), "Ableton")):
        if not os.path.isdir(base):
            continue
        for live_dir in sorted(os.listdir(base), reverse=True):
            target = os.path.join(base, live_dir, "User Remote Scripts", "ChatGPTBridge")
            if os.path.isdir(target):
                return target, live_dir
    return None, None


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="ableton-agent",
        description="Control Ableton Live with any LLM (OpenAI-compatible API).")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)

    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--dry-run", action="store_true",
                        help="print the plan without sending to Ableton")

    sp = sub.add_parser("run", help="one-shot: prompt -> plan -> execute in Live")
    sp.add_argument("prompt", nargs="+", help="what to build, e.g. 'tech house at 126 BPM'")
    sp.add_argument("--delay", type=float, default=0.15, help="seconds between commands")
    common(sp)
    sp.set_defaults(func=lambda a: setattr(a, "prompt", " ".join(a.prompt)) or cmd_run(a))

    sp = sub.add_parser("chat", help="interactive session (like opencode chat)")
    common(sp)
    sp.set_defaults(func=cmd_chat)

    sp = sub.add_parser("send", help="send one raw command (no LLM)")
    sp.add_argument("action", help="e.g. play, stop, set_tempo, describe_set")
    sp.add_argument("args", nargs="?", default="", help='JSON args, e.g. {"bpm":126}')
    common(sp)
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("install", help="install the ChatGPTBridge Remote Script into Ableton")
    sp.add_argument("--dest", help="path to Ableton's MIDI Remote Scripts folder")
    sp.set_defaults(func=cmd_install)

    sp = sub.add_parser("config", help="show current model/endpoint config")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("providers", help="list and switch localhost/free AI providers (ollama, 9router...)")
    sp.add_argument("--set", help="switch provider (ollama, lmstudio, 9router, openrouter-free, groq...)")
    sp.add_argument("--model", help="custom model name")
    sp.set_defaults(func=cmd_providers)

    sp = sub.add_parser("mcp", help="run native MCP (Model Context Protocol) server over stdio")
    sp.set_defaults(func=cmd_mcp)

    sp = sub.add_parser("describe", help="query active Ableton set state")
    sp.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for response")
    sp.set_defaults(func=cmd_describe)

    sp = sub.add_parser("theory", help="music theory & groove helper (chords, euclidean rhythms)")
    sp.add_argument("type", choices=["chord", "euclidean"], help="mode: chord or euclidean")
    sp.add_argument("--root", default="C3", help="root note (default: C3)")
    sp.add_argument("--chord-type", default="min7", help="chord type: maj, min, min7, maj7, etc.")
    sp.add_argument("--hits", type=int, default=3, help="number of rhythm hits (for euclidean)")
    sp.add_argument("--steps", type=int, default=8, help="number of steps (for euclidean)")
    sp.set_defaults(func=cmd_theory)

    sp = sub.add_parser("app", aliases=["gui"], help="launch macOS visual studio companion")
    sp.add_argument("--port", type=int, default=8765, help="local studio port (default 8765)")
    sp.add_argument("--no-open", action="store_true", help="do not auto-open browser")
    sp.set_defaults(func=cmd_app)

    sp = sub.add_parser("simulate", aliases=["sim"],
                        help="run an offline fake Ableton Live (test without Live installed)")
    sp.add_argument("--port", type=int, default=core.UDP_PORT, help="UDP port to listen on")
    sp.add_argument("--quiet", action="store_true", help="do not print set state changes")
    sp.set_defaults(func=cmd_simulate)

    sp = sub.add_parser("doctor", help="diagnose bridge install, Live connection and LLM config")
    sp.add_argument("--timeout", type=float, default=1.0, help="seconds to wait for Live")
    sp.set_defaults(func=cmd_doctor)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        # Default behavior: Launch Claude Code-style interactive terminal!
        from .terminal import run_terminal
        run_terminal()
        return
    args.func(args)


if __name__ == "__main__":
    main()
