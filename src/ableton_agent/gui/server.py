# -*- coding: utf-8 -*-
"""Local GUI server for ableton-agent.

Provides a lightweight, zero-dependency visual web studio for macOS users
to connect, configure, and control Ableton Live without touching a terminal.
"""

import http.server
import json
import os
import socket
import sys
import threading
import urllib.parse
import webbrowser

from .. import __version__, core, theory
from ..cli import cmd_install

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class StudioHandler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super(StudioHandler, self).__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            self._handle_status()
        elif parsed.path == "/api/describe":
            self._handle_describe()
        elif parsed.path == "/api/mcp-config":
            self._handle_mcp_config()
        else:
            # Fallback to static files
            super(StudioHandler, self).do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if parsed.path == "/api/send":
            self._handle_send(data)
        elif parsed.path == "/api/install":
            self._handle_install(data)
        elif parsed.path == "/api/prompt":
            self._handle_prompt(data)
        elif parsed.path == "/api/groove":
            self._handle_groove(data)
        elif parsed.path == "/api/config":
            self._handle_save_config(data)
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _handle_status(self):
        home = os.path.expanduser("~")
        mac_script_dir = os.path.join(home, "Library", "Preferences", "Ableton")
        win_script_dir = os.path.join(os.environ.get("APPDATA", home), "Ableton")
        installed = False
        detected_ver = None

        for base in (mac_script_dir, win_script_dir):
            if os.path.isdir(base):
                for d in sorted(os.listdir(base), reverse=True):
                    if d.startswith("Live"):
                        detected_ver = d
                        target = os.path.join(base, d, "User Remote Scripts", "ChatGPTBridge")
                        if os.path.isdir(target):
                            installed = True
                            break

        # Check bridge connection with a quick ping
        bridge_alive = False
        desc = core.send_command("describe_set", {}, wait_response=True, timeout=0.6)
        if desc and desc.get("status") == "ok":
            bridge_alive = True

        status = {
            "version": __version__,
            "bridge_installed": installed,
            "bridge_alive": bridge_alive,
            "detected_live": detected_ver or "Ableton Live 11/12",
            "host": core.UDP_HOST,
            "port": core.UDP_PORT,
            "model": core.current_model(),
            "endpoint": os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1",
            "has_key": bool(os.environ.get("OPENAI_API_KEY")),
        }
        self._send_json(status)

    def _handle_install(self, data):
        # Fake args object for cmd_install
        class Args:
            dest = data.get("dest")

        try:
            cmd_install(Args())
            self._send_json({"success": True, "message": "Installed ChatGPTBridge successfully!"})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, code=500)

    def _handle_send(self, data):
        action = data.get("action")
        args = data.get("args", {})
        resp = core.send_command(action, args, wait_response=True, timeout=1.2)
        self._send_json({"action": action, "response": resp or "sent"})

    def _handle_describe(self):
        resp = core.send_command("describe_set", {}, wait_response=True, timeout=1.5)
        self._send_json({"set": resp.get("result") if resp else None, "raw": resp})

    def _handle_prompt(self, data):
        prompt = data.get("prompt")
        dry_run = bool(data.get("dry_run", False))
        if not prompt:
            self._send_json({"error": "Prompt cannot be empty"}, code=400)
            return
        try:
            plan = core.get_plan(prompt, verbose=False)
            if not dry_run:
                core.send_plan(plan, delay=0.1)
            self._send_json({"success": True, "plan": plan, "dry_run": dry_run})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, code=500)

    def _handle_groove(self, data):
        mode = data.get("mode", "chord")
        if mode == "chord":
            root = data.get("root", "C3")
            chord_type = data.get("chord_type", "min7")
            pitches = theory.get_chord_notes(root, chord_type)
            notes = [{"pitch": p, "start": 0.0, "length": 2.0, "velocity": 105} for p in pitches]
            if data.get("humanize", True):
                notes = theory.humanize_notes(notes)
            # Send to Ableton if track and slot specified
            if "track_index" in data and "slot" in data:
                t_idx = int(data["track_index"])
                s_idx = int(data["slot"])
                core.send_command("create_clip", {"track_index": t_idx, "slot": s_idx, "length_beats": 4.0})
                core.send_command("add_notes", {"track_index": t_idx, "slot": s_idx, "notes": notes})
            self._send_json({"success": True, "chord": "%s %s" % (root, chord_type), "notes": notes})
        else:
            hits = int(data.get("hits", 3))
            steps = int(data.get("steps", 8))
            pattern = theory.euclidean_rhythm(hits, steps)
            step_len = 4.0 / steps
            notes = []
            for i, hit in enumerate(pattern):
                if hit:
                    notes.append({"pitch": 60, "start": round(i * step_len, 4), "length": 0.2, "velocity": 105})
            if data.get("humanize", True):
                notes = theory.humanize_notes(notes, swing=float(data.get("swing", 0.0)))
            if "track_index" in data and "slot" in data:
                t_idx = int(data["track_index"])
                s_idx = int(data["slot"])
                core.send_command("create_clip", {"track_index": t_idx, "slot": s_idx, "length_beats": 4.0})
                core.send_command("add_notes", {"track_index": t_idx, "slot": s_idx, "notes": notes})
            self._send_json({"success": True, "pattern": pattern, "notes": notes})

    def _handle_save_config(self, data):
        if "endpoint" in data:
            os.environ["LLM_BASE_URL"] = data["endpoint"]
        if "model" in data:
            os.environ["LLM_MODEL"] = data["model"]
        if "api_key" in data and data["api_key"]:
            os.environ["OPENAI_API_KEY"] = data["api_key"]
        self._send_json({"success": True, "message": "Config updated"})

    def _handle_mcp_config(self):
        exe = sys.executable
        cfg = {
            "mcpServers": {
                "ableton-agent": {
                    "command": "ableton-agent",
                    "args": ["mcp"]
                }
            }
        }
        self._send_json(cfg)


def start_server(port=8765, open_browser=True):
    """Start local GUI studio server."""
    server = http.server.HTTPServer(("127.0.0.1", port), StudioHandler)
    url = "http://127.0.0.1:%d" % port
    print("\n=======================================================")
    print("  🎹 Ableton Agent Studio (macOS Companion) is LIVE!")
    print("  👉 URL: %s" % url)
    print("  Press Ctrl+C to quit.")
    print("=======================================================\n")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStudio stopped.")
