# -*- coding: utf-8 -*-
"""Core engine: LLM planning (any OpenAI-compatible API) + UDP bridge to Live."""

import json
import os
import re
import socket
import time

UDP_HOST = os.environ.get("ABLETON_AGENT_HOST", "127.0.0.1")
UDP_PORT = int(os.environ.get("ABLETON_AGENT_PORT", "9000"))

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
- rename_track         {track_index: int, name: string}
- load_sample          {track_index: int, file: "kick_01.wav", slot: int(-1=auto)}
- create_clip          {track_index: int, slot: int, length_beats: float}
- add_notes            {track_index: int, slot: int,
                        notes: [{pitch: int(0-127), start: float(beats),
                                 length: float(beats), velocity: int(1-127)}]}
- fire_clip            {track_index: int, slot: int}
- set_volume           {track_index: int, value: 0.0-1.0  (1.0 = 0 dB)}
- set_pan              {track_index: int, value: -1.0..1.0}
- mute_track           {track_index: int, mute: bool}
- solo_track           {track_index: int, solo: bool}
- arm_track            {track_index: int, arm: bool}
- add_send             {track_index: int, bus_index: int, amount: 0.0-1.0}
- load_device          {track_index: int, device_name: "Reverb"|"Delay"|
                        "Glue Compressor"|"Compressor"|"EQ Eight"|...}
- set_device_param     {track_index: int, device_index: int,
                        param_name: "substring", value: 0.0-1.0}
- automate_mixer       {track_index: int, param: "volume"|"panning",
                        points: [{time: float(beats), value: 0.0-1.0}]}
- describe_set         {}   (logs current set state to Ableton's Log.txt)
- play {}  |  stop {}
- message              {text: string}  (status bar message in Live)

RULES:
- Sample library root is ~/Samples (configurable via SAMPLE_ROOTS in the
  Remote Script). Use realistic file names; the bridge fuzzy-searches by name.
- Beats: 1 bar of 4/4 = 4 beats. Pitches: middle C = 60, kick ~36,
  snare/clap ~38-40, closed hat ~42, open hat ~46.
- Order commands logically: tempo -> tracks -> clips/notes -> mix -> fx.
- Keep plans under 60 commands.
- Your entire reply must be ONLY the JSON object.
"""


def extract_json(text):
    """Tolerant JSON extraction (handles fences/chatter from local models)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return json.loads(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("model did not return JSON. Raw reply:\n" + text[:2000])


def make_client():
    from openai import OpenAI
    return OpenAI(
        base_url=os.environ.get("LLM_BASE_URL") or None,
        api_key=os.environ.get("OPENAI_API_KEY") or "not-needed",
    )


def current_model():
    return (os.environ.get("LLM_MODEL") or os.environ.get("GPT_MODEL")
            or "gpt-4o")


def get_plan(user_prompt, temperature=0.4, max_retries=2, verbose=True):
    client = make_client()
    model = current_model()
    if verbose:
        print("[agent] endpoint : %s" % (client.base_url or "https://api.openai.com/v1"))
        print("[agent] model    : %s" % model)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            kwargs = dict(model=model, temperature=temperature, messages=messages)
            try:
                resp = client.chat.completions.create(
                    response_format={"type": "json_object"}, **kwargs)
            except Exception:
                resp = client.chat.completions.create(**kwargs)
            return extract_json(resp.choices[0].message.content or "")
        except Exception as e:
            last_err = e
            print("[agent] attempt %d failed (%s); retrying..." % (attempt + 1, e))
            messages.append({"role": "user",
                             "content": "Not valid JSON. Reply with ONLY "
                                        '{"commands": [...]}.'})
    raise RuntimeError("could not get a valid plan: %s" % last_err)


def send_plan(plan, delay=0.15, dry_run=False):
    commands = plan.get("commands", [])
    print("[agent] %d commands" % len(commands))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for i, cmd in enumerate(commands, 1):
        line = json.dumps(cmd)
        print("  [%02d/%02d] %s %s" % (i, len(commands), cmd.get("action"),
                                       json.dumps(cmd.get("args", {}))[:80]))
        if not dry_run:
            sock.sendto(line.encode(), (UDP_HOST, UDP_PORT))
            time.sleep(delay)
    if not dry_run:
        print("[agent] done - check Ableton (Log.txt for details).")


def send_command(action, args=None, dry_run=False):
    """Send a single raw command without the LLM."""
    cmd = {"action": action, "args": args or {}}
    if dry_run:
        print(json.dumps(cmd))
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(json.dumps(cmd).encode(), (UDP_HOST, UDP_PORT))
    print("[agent] sent: %s" % json.dumps(cmd))
