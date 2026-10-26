# Hellboy Prod 1.2 - design

Goal: close the remaining gaps (Arrangement View, a second transport, no
terminal needed) without touching the frozen wire protocol or the
"handler -> HANDLERS -> registry" seam.

## 1. Requirements

Functional
- Arrangement View: list/place/create/delete arrangement clips, read and write
  their notes, record/overdub state, cue points (locators), view switching, and
  an auto-arranger that turns an ordered list of scenes into an arrangement.
- OSC: hardware/phone controllers (TouchOSC, Lemur, Max) can call any handler.
- Hellboy Studio: a desktop app so a producer never opens a terminal -
  install/uninstall, register agents, see and drive the set, the creative
  tools as forms, and a built-in assistant chat.

Non-functional
- Remote script stays standard library only, never touches Live off the main
  thread, never crashes Live. Every new LOM call is `hasattr`-guarded so older
  Live versions get a clear `reason`, not an exception.
- Still one self-contained binary per platform, nothing else to install.
- The app's local HTTP API must not be reachable by other web pages.

## 2. High-level design

```
 TouchOSC / Max ──UDP 8972 (OSC)──┐
                                  ▼
 Claude Code / Codex ─stdio MCP─► hellboy-bridge ─TCP 8971─► remote script ─► Live
                                  ▲                          (one queue, one
 Browser UI ◄─HTTP+SSE─► hellboy-app ───────── TCP 8971 ─────┘  handler table)
                          ├─ installer lib (same code as the CLI installer)
                          ├─ Live client  (same code as the bridge)
                          ├─ assistant    (Claude API tool loop over the registry)
                          └─ --mcp        (the app binary is also a bridge)
```

Both transports feed the same `(target, request)` queue that `_tick()` drains
on Live's main thread. An OSC reply target is an object with `sendall()`, so
the dispatcher does not know or care which transport a request came from.

## 3. Deep dive

### Arrangement (hb_arrangement.py)
| tool | LOM | guard |
|---|---|---|
| arrangement_state | song_length, current_song_time, record_mode, arrangement_overdub, back_to_arranger, cue_points | none (Live 9+) |
| arrangement_clips | track.arrangement_clips | Live 11+ |
| arrangement_place_clip | track.duplicate_clip_to_arrangement | Live 11+ |
| arrangement_create_midi_clip / _audio_clip | track.create_midi_clip / create_audio_clip | Live 12+ |
| arrangement_delete_clip | track.delete_clip | Live 12+ |
| arrangement_notes_get / _set | clip.get_notes_extended / add_new_notes | Live 11+ |
| arrangement_record, arrangement_back_to_arranger, arrangement_show | song / application view | - |
| cue_list / cue_add / cue_jump / cue_rename / cue_delete | song.cue_points, set_or_delete_cue | - |
| arrangement_from_scenes | duplicate_clip_to_arrangement in a loop, cue per section | Live 11+ |

Times are in beats; helpers accept bars where producers think in bars.

### OSC (hb_osc.py)
- Address `/hellboy/<method>`. Arguments either one JSON object string, or
  positional values mapped onto the handler's parameter names (read with
  `inspect`), so `/hellboy/track_set_volume 2 0.7` works from a fader.
- Reply: `/hellboy/reply <method> <ok 1|0> <json>` to the sender, or to
  `HELLBOY_OSC_REPLY_PORT`. Bundles are unpacked.
- Binds 127.0.0.1:8972 by default; `HELLBOY_OSC_HOST=0.0.0.0` opts into LAN
  controllers; `HELLBOY_OSC_PORT=0` disables it. A busy port disables OSC with a
  log line - TCP keeps working.

### Hellboy Studio (app/)
- One Node binary. No args: start an HTTP server on 127.0.0.1 with a random
  port and open the browser. `--mcp`: act as the MCP bridge (so agents can be
  registered against the app binary itself).
- The remote script is embedded at build time, so the app alone can install
  it.
- Security: per-launch random token (in the URL fragment, never sent as a
  request), required as a header on every `/api` call; the Host header must
  be the loopback address (DNS-rebinding defence); `/api/call` only accepts
  registry methods and validates params with the same zod schemas.
- Single instance: `~/.hellboy/app.json` records port + token; a second launch
  just reopens the browser on the running instance. The server exits after a
  few minutes with no open UI.
- Assistant: `@anthropic-ai/sdk`, streaming manual loop, `claude-opus-5-5`,
  adaptive thinking, the registry as tools (JSON schema generated from zod,
  inputs re-validated with zod before they reach Live), prompt caching on the
  tool list, server-side refusal fallback. API key from the app settings
  (stored 0600 in `~/.hellboy/config.json`) or `ANTHROPIC_API_KEY`.

## 4. Reliability
- Every agent call is one undo step, so an assistant mistake is one Ctrl+Z.
- Live drops -> in-flight calls fail at once; the next call reconnects.
- OSC never blocks: the UDP thread only parses and enqueues.

## 5. Trade-offs
- Browser UI instead of Electron/Tauri: about 50 MB instead of 150+ MB, no new
  toolchain, the same pkg pipeline, and the same UI works on every platform.
  The cost is that it opens in a browser tab rather than its own window.
- macOS: shipped as `Hellboy Studio.app` (LSUIElement, no Dock icon) so a
  double click does not open Terminal. Windows: the app exe is patched to the
  GUI subsystem so no console window appears.
- An embedded LLM loop needs an API key; without one the app still does
  everything except chat.

## 6. Revisit as it grows
- Arrangement editing beyond Live's API (time selection, cut/insert time) needs
  Live to expose it.
- A native window (webview) if users want the app outside the browser.
- OSC push (subscribe to tempo/playing changes) via Live listeners.
