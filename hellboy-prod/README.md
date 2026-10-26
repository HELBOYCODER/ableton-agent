# Hellboy Prod

**Talk to your running music production session from your terminal.**

Hellboy Prod connects a terminal coding agent (any MCP client) to a live
DAW session. The agent gets ~95 tools to read the set and create or edit
tracks, clips, MIDI notes, devices, automation, the mix, and a "quick loop"
slice-and-shuffle generator — while you keep manual control and the project
stays editable.

```
agent  --stdio (MCP)-->  hellboy-bridge  --TCP/JSON-->  remote script  -->  DAW
```

## Components

| Path                        | What it is                                           |
| --------------------------- | ---------------------------------------------------- |
| `remote-script/HellboyProd` | Python remote script, standard library only          |
| `bridge/`                   | TypeScript MCP server (stdio transport)              |
| `installer/`                | Cross-platform installer / MCP registration          |
| `mock-live/`                | Fake DAW server so CI can run without the DAW        |

## Quick start

```bash
npm install
npm run build        # compile mock-live, bridge, installer
npm test             # spins up mock-live and round-trips the bridge
npm run test:py      # load the remote script as Live does, against a fake LOM
npm run lint:py      # byte-compile the remote script
npm run bundle       # bridge/build/bridge.cjs + installer/build/installer.cjs
```

### Install for real use

```bash
node installer/dist/index.js install     # copy remote script + write .mcp.json
node installer/dist/index.js status
node installer/dist/index.js uninstall
```

Then in the DAW: **Preferences -> Link / MIDI -> Control Surface -> Hellboy Prod**
(set an unused Input/Output pair so the surface activates). Start your agent in
a project folder; it reads `.mcp.json` automatically.

## Wire protocol

TCP on `127.0.0.1:8971` (override with `HELLBOY_PORT`), one JSON object per line:

```
-> {"id":7,"method":"clip_set_notes","params":{...}}
<- {"id":7,"ok":true,"result":{...}}
```

Handshake is a `hello` call that returns the product, API version, port,
DAW version and the full method list.

## Building binaries (macOS + Windows)

`.github/workflows/hellboy-release.yml` (repo root) builds on push of a `hellboy-v*` tag: a matrix over
macos-14 (arm64), macos-15-intel (x64) and windows-latest (x64), bundles with
esbuild, compiles with `@yao-pkg/pkg`, ad-hoc codesigns on macOS, and publishes a
release with the six binaries, the zipped remote script and `SHA256SUMS.txt`.

End users unzip `hellboyprod-remote-script.zip` next to the installer and
bridge binaries, then run `hellboy-installer-<platform> install`.

```bash
git tag hellboy-v1.0.0
git push origin hellboy-v1.0.0
```

See `BUILD_GUIDE.txt` for the full build, run and troubleshooting guide, and
`SPEC.md` for the original design specification.

## License

MIT — see `LICENSE`.
