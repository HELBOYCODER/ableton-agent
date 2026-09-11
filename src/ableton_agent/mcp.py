# -*- coding: utf-8 -*-
"""Model Context Protocol (MCP) Server for ableton-agent.

Exposes Ableton Live control tools to AI clients (Claude Desktop, Cursor, Minis)
via JSON-RPC 2.0 over standard I/O (zero external dependencies).
"""

import io
import json
import os
import sys

from . import __version__, core, theory


def _make_error(code, message, req_id=None):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _make_result(result, req_id):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


TOOLS = [
    {
        "name": "ableton_plan_and_run",
        "description": "Send natural language prompt to AI music producer to construct a track, rhythm, or arrangement in Ableton Live.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Musical description (e.g. 'Tech house groove at 126 BPM with rolling bass and 909 drums')",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, returns the planned JSON commands without sending to Live",
                    "default": False,
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "ableton_send_command",
        "description": "Execute a specific Ableton Live action directly (e.g. play, stop, set_tempo, create_midi_track, add_notes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action name: play, stop, set_tempo, create_midi_track, create_audio_track, load_sample, create_clip, add_notes, fire_clip, set_volume, set_pan, mute_track, solo_track, load_device, set_device_param, describe_set",
                },
                "args": {
                    "type": "object",
                    "description": "Arguments dictionary for the action",
                    "default": {},
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "ableton_describe_set",
        "description": "Request Live set overview (tempo, tracks, loaded devices, clips) to inspect state before producing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "description": "Wait time in seconds for Live response",
                    "default": 1.5,
                }
            },
        },
    },
    {
        "name": "ableton_generate_groove",
        "description": "Generate music-theory compliant chords, scales, or Euclidean syncopated rhythms with humanized velocity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["chord", "euclidean"],
                    "description": "'chord' builds chord notes; 'euclidean' generates algorithmic syncopated rhythm",
                },
                "root": {
                    "type": "string",
                    "description": "Root note for chords (e.g. 'C3', 'A2', 'F#3')",
                    "default": "C3",
                },
                "chord_type": {
                    "type": "string",
                    "description": "Chord type: maj, min, min7, maj7, min9, dim, sus4",
                    "default": "min7",
                },
                "hits": {
                    "type": "integer",
                    "description": "Number of rhythm pulses for Euclidean mode (e.g. 3, 5, 7)",
                    "default": 3,
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of grid steps (e.g. 8 or 16)",
                    "default": 8,
                },
                "humanize": {
                    "type": "boolean",
                    "description": "Apply velocity swing and human timing jitter",
                    "default": True,
                },
                "track": {
                    "type": "string",
                    "description": "Optional track name (or index) to write the result into; omit to only return notes",
                },
                "slot": {
                    "type": "integer",
                    "description": "Clip slot to write into when 'track' is given",
                    "default": 0,
                },
            },
            "required": ["mode"],
        },
    },
    {
        "name": "ableton_get_status",
        "description": "Check ableton-agent configuration, active LLM provider, and UDP bridge settings.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _handle_tool_call(name, args):
    if name == "ableton_get_status":
        bridge = core.send_command("ping", {}, wait_response=True, timeout=0.6, verbose=False)
        info = {
            "version": __version__,
            "llm_endpoint": core.current_endpoint(),
            "model": core.current_model(),
            "api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
            "udp_target": "%s:%d" % (core.UDP_HOST, core.UDP_PORT),
            "bridge_connected": bool(bridge and bridge.get("status") == "ok"),
            "bridge": (bridge or {}).get("result"),
        }
        return json.dumps(info, indent=2)

    elif name == "ableton_plan_and_run":
        prompt = args.get("prompt")
        if not prompt:
            raise ValueError("prompt is required")
        dry_run = bool(args.get("dry_run", False))
        plan = core.get_plan(prompt, verbose=False)
        results = core.send_plan(plan, dry_run=dry_run, verbose=False)
        failed = [
            {"action": r["command"]["action"],
             "error": (r["response"] or {}).get("error", "no response from Live bridge")}
            for r in results if not r["ok"]
        ]
        res = {
            "status": "planned" if dry_run else ("executed" if not failed else "partial"),
            "commands_count": len(results),
            "failed": failed,
            "plan": plan,
        }
        return json.dumps(res, indent=2)

    elif name == "ableton_send_command":
        action = args.get("action")
        if not action:
            raise ValueError("action is required")
        action_args = args.get("args", {}) or {}
        resp = core.send_command(action, action_args, wait_response=True, timeout=1.5, verbose=False)
        return json.dumps({"action": action, "response": resp or "sent"}, indent=2)

    elif name == "ableton_describe_set":
        timeout = float(args.get("timeout", 1.5))
        resp = core.send_command("describe_set", {}, wait_response=True, timeout=timeout, verbose=False)
        if resp:
            return json.dumps(resp, indent=2)
        return "describe_set command dispatched to Ableton Live (check Ableton Log.txt or verify ChatGPTBridge connection)."

    elif name == "ableton_generate_groove":
        mode = args.get("mode", "chord")
        if mode == "chord":
            root = args.get("root", "C3")
            ctype = args.get("chord_type", "min7")
            pitches = theory.get_chord_notes(root, ctype)
            notes = [{"pitch": p, "start": 0.0, "length": 2.0, "velocity": 100} for p in pitches]
            if args.get("humanize", True):
                notes = theory.humanize_notes(notes)
            out = {"chord": "%s %s" % (root, ctype), "pitches": pitches, "notes": notes}
        else:
            hits = int(args.get("hits", 3))
            steps = max(1, int(args.get("steps", 8)))
            pattern = theory.euclidean_rhythm(hits, steps)
            notes = []
            step_len = 4.0 / steps
            for i, hit in enumerate(pattern):
                if hit:
                    notes.append({"pitch": 36, "start": round(i * step_len, 4), "length": 0.2, "velocity": 105})
            if args.get("humanize", True):
                notes = theory.humanize_notes(notes, swing=0.1)
            out = {"pattern": pattern, "hits": hits, "steps": steps, "notes": notes}

        if args.get("track") is not None and notes:
            out["sent"] = _write_notes_to_live(args["track"], int(args.get("slot", 0)), notes)
        return json.dumps(out, indent=2)

    raise ValueError("Unknown tool: %s" % name)


def _write_notes_to_live(track, slot, notes):
    """Create a clip on `track` and write `notes` into it; return the acks."""
    results = core.send_plan({"commands": [
        {"action": "create_clip",
         "args": {"track": track, "slot": slot, "length_beats": 4.0}},
        {"action": "add_notes",
         "args": {"track": track, "slot": slot, "notes": notes}},
    ]}, verbose=False)
    return [{"action": r["command"]["action"], "ok": r["ok"],
             "error": (r["response"] or {}).get("error")} for r in results]


def _call_tool_isolated(name, args):
    """Run a tool with stdout captured.

    stdout is the JSON-RPC transport: a stray print from the planner would
    corrupt the stream and disconnect the MCP client.
    """
    buffer = io.StringIO()
    with core.stdout_to(buffer):
        out = _handle_tool_call(name, args)
    noise = buffer.getvalue()
    if noise.strip():
        sys.stderr.write(noise)
        sys.stderr.flush()
    return out


def run_mcp_server():
    """Main MCP stdio message loop."""
    sys.stderr.write("ableton-agent MCP Server v%s started on stdio\n" % __version__)
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            sys.stdout.write(json.dumps(_make_error(-32700, "Parse error: %s" % e)) + "\n")
            sys.stdout.flush()
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {}) or {}

        # Notifications (no id)
        if req_id is None:
            continue

        if method == "initialize":
            resp = _make_result({
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "ableton-agent",
                    "version": __version__,
                },
            }, req_id)
        elif method == "ping":
            resp = _make_result({}, req_id)
        elif method == "tools/list":
            resp = _make_result({"tools": TOOLS}, req_id)
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {}) or {}
            try:
                text_out = _call_tool_isolated(tool_name, tool_args)
                resp = _make_result({
                    "content": [{"type": "text", "text": str(text_out)}],
                    "isError": False,
                }, req_id)
            except Exception as e:
                resp = _make_result({
                    "content": [{"type": "text", "text": "Error: %s" % e}],
                    "isError": True,
                }, req_id)
        else:
            resp = _make_error(-32601, "Method not found: %s" % method, req_id)

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
