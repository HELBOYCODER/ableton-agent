# -*- coding: utf-8 -*-
"""Core engine: LLM planning (any OpenAI-compatible API) + UDP bridge to Live."""

import contextlib
import json
import os
import re
import socket
import sys
import time

UDP_HOST = os.environ.get("ABLETON_AGENT_HOST", "127.0.0.1")
UDP_PORT = int(os.environ.get("ABLETON_AGENT_PORT", "9000"))

# Live's normalised mixer volume where 0.85 == 0 dB.
UNITY_VOLUME = 0.85

SYSTEM_PROMPT = """You are a music-producer agent controlling Ableton Live 11/12
through a Python Remote Script called ChatGPTBridge. The user describes a
track; you output a JSON plan of commands that builds it.

OUTPUT FORMAT (strict JSON, no markdown, no prose):
{"commands": [ {"action": "<name>", "args": {...}}, ... ]}

AVAILABLE ACTIONS (exact names):
- set_tempo            {bpm: float}
- rename_project       {name: string}
- create_midi_track    {index: int (-1 = append), name: string}
- create_audio_track   {index: int (-1 = append), name: string}
- create_return_track  {name: string}
- rename_track         {track: <track ref>, name: string}
- load_sample          {track: <track ref>, file: "kick_01.wav", slot: int(-1=auto)}
- create_clip          {track: <track ref>, slot: int, length_beats: float}
- add_notes            {track: <track ref>, slot: int,
                        notes: [{pitch: int(0-127), start: float(beats),
                                 length: float(beats), velocity: int(1-127)}]}
- fire_clip            {track: <track ref>, slot: int}
- set_volume           {track: <track ref>, value: 0.0-1.0  (0.85 = 0 dB)}
- set_pan              {track: <track ref>, value: -1.0..1.0}
- mute_track           {track: <track ref>, mute: bool}
- solo_track           {track: <track ref>, solo: bool}
- arm_track            {track: <track ref>, arm: bool}
- add_send             {track: <track ref>, bus_index: int, amount: 0.0-1.0}
- load_device          {track: <track ref>, device_name: "Operator"|"Drum Rack"|
                        "Reverb"|"Delay"|"Glue Compressor"|"EQ Eight"|...}
                       device_name may be a LIST of candidates tried in order,
                       e.g. ["Kit-Core 909", "Drum Rack"].
- set_device_param     {track: <track ref>, device_index: int,
                        param_name: "substring", value: 0.0-1.0}
- automate_mixer       {track: <track ref>, param: "volume"|"panning",
                        points: [{time: float(beats), value: 0.0-1.0}]}
- describe_set         {}   (returns the current set state)
- play {}  |  stop {}
- message              {text: string}  (status bar message in Live)

TRACK REFERENCES ("track" or "track_index"):
- ALWAYS address a track you created by its NAME, e.g. {"track": "Sub Bass"}.
  New tracks are appended AFTER the tracks the user already has, so absolute
  indices like 0/1/2 point at the WRONG track. Names are resolved by the
  bridge. -1 means "the track created most recently".

RULES:
- A new MIDI track has NO instrument and is SILENT. After creating a MIDI
  track, always load_device an instrument on it before writing notes:
  drums -> ["Kit-Core 909", "Kit-Core 808", "Drum Rack"],
  bass -> ["Bass", "Operator"], keys/pads -> ["Grand Piano", "Wavetable"].
- Sample library root is ~/Samples (configurable via ABLETON_SAMPLE_ROOTS).
  Use realistic file names; the bridge fuzzy-searches by name.
- Beats: 1 bar of 4/4 = 4 beats. Pitches: middle C (Live's C3) = 60,
  kick ~36, snare/clap ~38-40, closed hat ~42, open hat ~46.
- DYNAMICS & GROOVE: Avoid flat velocity 100 on every note! Accent downbeats
  (vel 95-115), medium offbeats (vel 75-88), ghost notes (vel 45-60). Vary note
  lengths (e.g. staccato 0.125 vs sustained 0.5/1.0 beats) and apply syncopation.
- Order commands logically: tempo -> tracks -> clips/notes -> mix -> fx.
- Keep plans under 60 commands.
- Your entire reply must be ONLY the JSON object.
"""

# action -> (required arg names, known arg names)
COMMAND_SCHEMA = {
    "ping": ((), ()),
    "set_tempo": (("bpm",), ("bpm",)),
    "rename_project": (("name",), ("name",)),
    "create_midi_track": ((), ("index", "name")),
    "create_audio_track": ((), ("index", "name")),
    "create_return_track": ((), ("name",)),
    "delete_track": ((), ("track", "track_index", "track_name")),
    "rename_track": (("name",), ("track", "track_index", "track_name", "name")),
    "load_sample": (("file",), ("track", "track_index", "track_name", "file", "slot")),
    "create_clip": ((), ("track", "track_index", "track_name", "slot", "length_beats", "replace")),
    "add_notes": (("notes",), ("track", "track_index", "track_name", "slot", "notes", "replace", "length_beats")),
    "set_notes": (("notes",), ("track", "track_index", "track_name", "slot", "notes", "length_beats")),
    "fire_clip": ((), ("track", "track_index", "track_name", "slot")),
    "delete_clip": ((), ("track", "track_index", "track_name", "slot")),
    "set_volume": (("value",), ("track", "track_index", "track_name", "value")),
    "set_pan": (("value",), ("track", "track_index", "track_name", "value")),
    "mute_track": ((), ("track", "track_index", "track_name", "mute")),
    "solo_track": ((), ("track", "track_index", "track_name", "solo")),
    "arm_track": ((), ("track", "track_index", "track_name", "arm")),
    "add_send": ((), ("track", "track_index", "track_name", "bus_index", "amount")),
    "load_device": (("device_name",), ("track", "track_index", "track_name", "device_name")),
    "set_device_param": (("param_name", "value"), ("track", "track_index", "track_name", "device_index", "param_name", "value")),
    "automate_mixer": ((), ("track", "track_index", "track_name", "param", "points")),
    "describe_set": ((), ()),
    "play": ((), ()),
    "stop": ((), ()),
    "message": (("text",), ("text",)),
}

# Aliases models like to invent.
ACTION_ALIASES = {
    "tempo": "set_tempo",
    "set_bpm": "set_tempo",
    "add_midi_track": "create_midi_track",
    "new_midi_track": "create_midi_track",
    "add_audio_track": "create_audio_track",
    "add_track": "create_midi_track",
    "add_clip": "create_clip",
    "new_clip": "create_clip",
    "write_notes": "add_notes",
    "insert_notes": "add_notes",
    "start": "play",
    "start_playback": "play",
    "stop_playback": "stop",
    "volume": "set_volume",
    "pan": "set_pan",
    "add_device": "load_device",
}


def extract_json(text):
    """Tolerant JSON extraction (handles fences/chatter from local models)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("model did not return JSON. Raw reply:\n" + text[:2000])


_FLOAT_ARGS = ("bpm", "value", "length_beats", "amount")
_INT_ARGS = ("slot", "index", "track_index", "bus_index", "device_index")


def _coerce_note(note):
    """Clamp one note dict into what Live accepts."""
    if not isinstance(note, dict):
        raise ValueError("note must be an object")
    pitch = int(round(float(note.get("pitch", note.get("note", 60)))))
    start = float(note.get("start", note.get("time", 0.0)))
    length = float(note.get("length", note.get("duration", 0.25)))
    velocity = int(round(float(note.get("velocity", 100))))
    return {
        "pitch": max(0, min(127, pitch)),
        "start": max(0.0, round(start, 6)),
        "length": max(0.01, round(length, 6)),
        "velocity": max(1, min(127, velocity)),
    }


def _coerce_args(args):
    out = dict(args)
    for key in _FLOAT_ARGS:
        if key in out:
            out[key] = float(out[key])
    for key in _INT_ARGS:
        if key in out:
            out[key] = int(out[key])
    if "notes" in out:
        notes = out["notes"]
        if not isinstance(notes, (list, tuple)):
            raise ValueError("notes must be a list")
        out["notes"] = [_coerce_note(n) for n in notes]
        if not out["notes"]:
            raise ValueError("notes is empty")
    return out


def normalize_plan(plan):
    """Coerce whatever the model produced into a valid, sendable plan.

    Models routinely return a bare list, wrap commands under "plan"/"actions",
    use `name`/`command` instead of `action`, or inline args at the top level.
    Unknown/incomplete commands are dropped instead of being fired at Live.
    """
    if isinstance(plan, list):
        plan = {"commands": plan}
    if not isinstance(plan, dict):
        raise ValueError("plan must be a JSON object or list of commands")

    raw = None
    for key in ("commands", "plan", "actions", "steps"):
        value = plan.get(key)
        if isinstance(value, list):
            raw = value
            break
    if raw is None:
        raw = []

    commands, dropped = [], []
    for item in raw:
        if not isinstance(item, dict):
            dropped.append(repr(item)[:60])
            continue
        action = item.get("action") or item.get("name") or item.get("command")
        if not isinstance(action, str):
            dropped.append(repr(item)[:60])
            continue
        action = ACTION_ALIASES.get(action.strip().lower(), action.strip().lower())
        if action not in COMMAND_SCHEMA:
            dropped.append(action)
            continue
        required, known = COMMAND_SCHEMA[action]
        args = item.get("args") or item.get("arguments") or item.get("params")
        if not isinstance(args, dict):
            args = {k: v for k, v in item.items()
                    if k not in ("action", "name", "command", "args", "arguments", "params")}
        args = {k: v for k, v in args.items() if k in known}
        if any(k not in args for k in required):
            dropped.append("%s(missing %s)" % (action, ",".join(k for k in required if k not in args)))
            continue
        try:
            args = _coerce_args(args)
        except (TypeError, ValueError):
            dropped.append("%s(bad args)" % action)
            continue
        commands.append({"action": action, "args": args})

    out = dict(plan)
    out["commands"] = commands
    if dropped:
        out["dropped"] = dropped
    return out


def make_client():
    from openai import OpenAI
    return OpenAI(
        base_url=os.environ.get("LLM_BASE_URL") or None,
        api_key=os.environ.get("OPENAI_API_KEY") or "not-needed",
    )


def current_model():
    return (os.environ.get("LLM_MODEL") or os.environ.get("GPT_MODEL")
            or "gpt-4o")


def current_endpoint():
    return os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1"


@contextlib.contextmanager
def stdout_to(stream):
    """Temporarily redirect prints (protects stdio protocols like MCP)."""
    saved = sys.stdout
    sys.stdout = stream
    try:
        yield
    finally:
        sys.stdout = saved


def get_plan(user_prompt, temperature=0.4, max_retries=2, verbose=True):
    from . import providers

    # 1. Auto-detect running local provider if on default OpenAI without key
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("LLM_BASE_URL"):
        local_detected = providers.detect_local_providers()
        if local_detected:
            best = local_detected[0]
            providers.switch_provider(best["key"])
            if verbose:
                print("[agent] auto-detected running local engine: %s (%s)" % (best["name"], best["default_model"]))

    # 2. If still no API key and no local endpoint, use built-in offline producer
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("LLM_BASE_URL"):
        if verbose:
            print("[agent] using offline music producer (no API key required; /provider to switch)")
        return providers.generate_heuristic_plan(user_prompt)

    model = current_model()
    if verbose:
        print("[agent] endpoint : %s" % current_endpoint())
        print("[agent] model    : %s" % model)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            client = make_client()
            kwargs = dict(model=model, temperature=temperature, messages=messages)
            try:
                resp = client.chat.completions.create(
                    response_format={"type": "json_object"}, **kwargs)
            except Exception:
                resp = client.chat.completions.create(**kwargs)
            plan = normalize_plan(extract_json(resp.choices[0].message.content or ""))
            if not plan["commands"]:
                raise ValueError("plan contained no usable commands")
            if plan.get("dropped") and verbose:
                print("[agent] ignored %d invalid command(s): %s"
                      % (len(plan["dropped"]), ", ".join(plan["dropped"][:5])))
            return plan
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                if verbose:
                    print("[agent] attempt %d failed (%s); retrying..." % (attempt + 1, e))
                messages.append({"role": "user",
                                 "content": "Not valid JSON. Reply with ONLY "
                                            '{"commands": [...]}.'})

    # If LLM failed, gracefully fall back to heuristic producer
    if verbose:
        print("[agent] LLM unavailable (%s); falling back to offline music generator." % last_err)
    plan = providers.generate_heuristic_plan(user_prompt)
    plan["llm_error"] = str(last_err)
    return plan


def send_plan(plan, delay=0.08, dry_run=False, verbose=True, timeout=1.5, on_result=None):
    """Send every command of a plan, waiting for the bridge's ack each time.

    Returns a list of {command, response, ok} so callers can report real
    per-step success instead of assuming UDP arrived. `on_result` is called as
    (index, total, command, ok, response) after each command, for live UIs.
    """
    plan = normalize_plan(plan)
    commands = plan.get("commands", [])
    results = []
    if verbose:
        print("[agent] %d commands" % len(commands))

    sock = None
    if not dry_run:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
    bridge_silent = False
    try:
        for i, cmd in enumerate(commands, 1):
            payload = dict(cmd)
            payload["id"] = i
            if verbose:
                print("  [%02d/%02d] %s %s" % (i, len(commands), cmd.get("action"),
                                               json.dumps(cmd.get("args", {}))[:80]))
            if dry_run:
                results.append({"command": cmd, "ok": True, "response": None})
                if on_result:
                    on_result(i - 1, len(commands), cmd, True, None)
                continue
            resp = None
            try:
                sock.sendto(json.dumps(payload).encode("utf-8"), (UDP_HOST, UDP_PORT))
                if not bridge_silent:
                    resp = _recv_ack(sock, i)
                    if resp is None:
                        # Nothing is listening; don't burn `timeout` per command.
                        bridge_silent = True
            except Exception as e:
                resp = {"status": "error", "error": str(e)}
            ok = bool(resp and resp.get("status") == "ok")
            if verbose and not ok:
                print("        ! %s" % (resp.get("error") if resp else "no response from Live bridge"))
            results.append({"command": cmd, "ok": ok, "response": resp})
            if on_result:
                on_result(i - 1, len(commands), cmd, ok, resp)
            if delay:
                time.sleep(delay)
    finally:
        if sock is not None:
            sock.close()

    if verbose and not dry_run:
        failed = [r for r in results if not r["ok"]]
        if failed:
            print("[agent] %d/%d commands failed - is ChatGPTBridge selected as a "
                  "Control Surface in Live?" % (len(failed), len(results)))
        else:
            print("[agent] done - check Ableton (Log.txt for details).")
    return results


def _recv_ack(sock, cmd_id, attempts=4):
    """Read replies until the one matching cmd_id shows up (or we time out)."""
    for _ in range(attempts):
        try:
            data, _addr = sock.recvfrom(65535)
        except socket.timeout:
            return None
        try:
            resp = json.loads(data.decode("utf-8"))
        except Exception:
            continue
        if resp.get("id") in (None, cmd_id):
            return resp
    return None


def send_command(action, args=None, dry_run=False, wait_response=False, timeout=1.5, verbose=True):
    """Send a single raw command without the LLM, optionally waiting for a reply."""
    cmd = {"action": action, "args": args or {}}
    if dry_run:
        if verbose:
            print(json.dumps(cmd))
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if wait_response:
        sock.settimeout(timeout)
    try:
        sock.sendto(json.dumps(cmd).encode("utf-8"), (UDP_HOST, UDP_PORT))
        if verbose:
            print("[agent] sent: %s" % json.dumps(cmd))
        if wait_response:
            try:
                data, _ = sock.recvfrom(65535)
                return json.loads(data.decode("utf-8"))
            except socket.timeout:
                return None
            except Exception:
                return None
    finally:
        sock.close()


def describe_set(timeout=1.5):
    """Return the Live set dict, or None when the bridge is unreachable."""
    resp = send_command("describe_set", {}, wait_response=True, timeout=timeout, verbose=False)
    if resp and resp.get("status") == "ok":
        return resp.get("result")
    return None
