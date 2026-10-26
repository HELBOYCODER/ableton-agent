# BUILD SPEC — Hellboy Prod

A complete, production-ready product built from scratch to this spec. The
naming, file layout, tool names, README and license are original work.

## 1. PRODUCT
Name: Hellboy Prod
Tagline: "Talk to your music production session from your terminal."
Connects a terminal coding agent (any MCP-compatible client) to a RUNNING
DAW session (Live 11/12). The agent can read the session, create/edit MIDI
and audio clips, build effect chains, group tracks, load devices/samples from
the browser, write automation and mix — while the user keeps manual control and
the project stays editable.
Supported: macOS 11+ (arm64 + x64), Windows 10/11 (x64). No Max for Live required.

## 2. ARCHITECTURE — four components with hard boundaries
- **remote-script/** Python 3 remote script loaded by the DAW. Owns ALL Live
  Object Model access. Runs a newline-delimited JSON server on
  `127.0.0.1:8971`. STANDARD LIBRARY ONLY — zero third-party deps.
- **bridge/** TypeScript MCP server, stdio transport. Connects to the remote
  script socket and exposes MCP tools. Ships as a single-file binary per platform.
- **installer/** Copies the remote script into the DAW User Library and
  registers the MCP server with any detected CLI agent.
- **mock-live/** Fake LOM server used by CI (runners cannot run the DAW).

## 3. REPO LAYOUT
```
hellboy-prod/
  remote-script/HellboyProd/{__init__,hb_util,hb_tracks,hb_clips,hb_notes,
    hb_devices,hb_browser,hb_automation,hb_mix,hb_quickloop,hb_license}.py
  bridge/src/{index,live-client,registry}.ts
  bridge/test/roundtrip.test.ts
  installer/src/index.ts
  mock-live/src/index.ts
  .github/workflows/{ci,release}.yml
  .mcp.json
  LICENSE (MIT)
  README.md
  BUILD_GUIDE.txt
```

## 4. WIRE PROTOCOL (frozen)
TCP `127.0.0.1:8971`, newline-delimited UTF-8 JSON.
```
request  {"id":int,"method":str,"params":{...}}
response {"id":int,"ok":true,"result":{...}}
         {"id":int,"ok":false,"error":"Type: msg"}
```
Handshake: `{"id":1,"method":"hello",...}` -> `{"ok":true,"result":{"product":"Hellboy Prod","api":1,...}}`
Methods are snake_case and domain-prefixed. Port overridable with `HELLBOY_PORT`.
A handler may return the DEFERRED sentinel; the reply is then sent later via
`ctx.reply_later()` (mix_balance samples meters over several ticks).

## 5. REMOTE SCRIPT — CRITICAL RULES
- Subclass `_Framework.ControlSurface`.
- NEVER touch the Live API from the socket thread. Socket threads only append
  `(conn, request)` to a queue; process it on the MAIN thread from
  `self.schedule_message(1, self._tick)`.
- Wrap every handler in try/except; always send a JSON reply, never crash.
- Log via `self.log_message`. Guard Live 11 vs 12 with `hasattr()`.
- Notes: write with `Live.Clip.MidiNoteSpecification` + `clip.add_new_notes()`;
  read with `clip.get_notes_extended()`.
- Browser: `Live.Application.get_application().browser`, load via
  `browser.load_item()` onto `song.view.selected_track`.
- Handlers live in `hb_*.py`, each exposing a `HANDLERS` dict merged by `__init__`.

## 6. MCP TOOL SURFACE
session_state/overview/set_tempo/set_signature/save/undo/redo/capture_scene/
set_master_volume; transport_play/stop/seek/set_loop;
track_list/brief/create_midi/create_audio/create_return/delete/duplicate/
rename/color/set_volume/set_pan/mute/solo/arm/set_send/select/group/move/
fold/freeze/unfreeze;
clip_list/info/create/delete/duplicate/rename/color/set_loop/set_markers/
set_warp/fire/stop/transpose;
scene_list/create/delete/fire/rename/duplicate;
notes_get/stats/set/add/clear/transpose/velocity/length_scale/range/quantize/
humanize/legato/shuffle_time;
device_list/params/get_param/set_param/set_active/delete/move/chains/
chain_devices/add;
browser_roots/children/search/item/load;
automation_get/write/clear/list/clear_all;
mix_report/balance/chain; quickloop_generate/scatter; license_check/status.
Every tool returns a JSON text content block. Use zod for all schemas.

## 7. QUICK LOOP + SHUFFLE
Takes a source clip: slice it, randomize order/pitch/reverse, and write the
result as a new clip. Exposed as `quickloop_generate` (and `quickloop_scatter`)
with a seed param.

## 8. INSTALLER
Detect OS, copy `remote-script/HellboyProd` into the DAW User Library Remote
Scripts folder, then register the MCP server: Claude Code via `claude mcp add`,
Codex via `~/.codex/config.toml [mcp_servers.hellboy]`, and always write a
project `.mcp.json`. Print clear next-step instructions.

## 9. CI/CD
- `ci.yml`: matrix ubuntu/macos-14/windows-latest -> npm ci -> build -> unit
  tests against mock-live -> lint:py.
- `release.yml`: on tag `v*` -> matrix (macos-14 node20-macos-arm64,
  macos-13 node20-macos-x64, windows-latest node20-win-x64) -> esbuild bundle
  -> pkg compile -> ad-hoc codesign on macOS -> upload artifacts -> GitHub
  Release with binaries, zipped remote script, and SHA256 checksums.

## 10. ACCEPTANCE
- `npm test` passes on all three OSes with mock-live.
- `npm run build` + `npm run bundle` produce working single-file binaries on
  mac arm64, mac x64 and win x64.
- Tagging `v1.0.0` produces a release with all binaries + remote script zip.
- README documents install, the control-surface step, and the CLI setup.
