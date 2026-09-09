# ableton-agent 🎹🤖

Control **Ableton Live 11/12 with any LLM** — an opencode-style CLI & native **MCP Server** for
AI-driven music production. Model-agnostic: OpenAI, Ollama, LM Studio,
DeepSeek, Groq, OpenRouter, or any OpenAI-compatible endpoint.

```
you:  "make a tech house track at 126 BPM"
      -> LLM builds a dynamic JSON command plan
      -> ableton-agent streams it over UDP (with bidirectional ACK)
      -> ChatGPTBridge Remote Script executes it inside Ableton
```

## Install

```bash
pip install git+https://github.com/HELBOYCODER/ableton-agent.git
# or from a release wheel:
pip install ableton_agent-0.2.1-py3-none-any.whl

# install the Ableton Remote Script (auto-detects your Live version):
ableton-agent install
# then: restart Ableton > Preferences > Link/Tempo/MIDI
#       > Control Surface = ChatGPTBridge
```

## macOS Visual Studio (Zero Setup) 🖥️🎹

For musicians & producers who prefer a visual interface without using the terminal:

```bash
ableton-agent app    # launches macOS visual companion
# or on Mac: double-click AbletonAgent.app / AbletonAgent.command
```

- **1-Click Auto-Install**: Detects Live 11/12 and installs `ChatGPTBridge` with one tap.
- **Visual AI Producer**: Pick models (OpenAI, Ollama Free, LM Studio, Groq, DeepSeek) and click instant genre presets.
- **16-Step Euclidean Sequencer**: Interactive illuminated LED step sequencer with Swing & Velocity Humanizer.
- **Harmonic Chord Generator**: Interactive chord pads with scale theory.
- **Live Project Inspector**: Live status of all active tracks, instruments, audio effects, and BPM.
- **Claude & Cursor Integration**: 1-click button to copy your MCP server config.

## CLI (opencode-style)

```bash
# AI Music Generation
ableton-agent run "make a tech house track at 126 BPM, intro build drop outro"
ableton-agent run --dry-run "lo-fi beat at 82 BPM"   # print plan, don't touch Live

# Interactive session (opencode chat style)
ableton-agent chat          # ':dry' toggle, ':config', 'exit'

# Inspect Live set state (bidirectional query)
ableton-agent describe      # dumps tracks, loaded devices, clips, BPM

# Music Theory & Groove engine
ableton-agent theory chord --root A2 --chord-type min7
ableton-agent theory euclidean --hits 5 --steps 16

# Direct commands (no LLM)
ableton-agent send play
ableton-agent send set_tempo '{"bpm": 126}'

ableton-agent config        # show active model / endpoint
ableton-agent --version
```

## Native Model Context Protocol (MCP) Server 🔌

`ableton-agent` includes a built-in zero-dependency MCP server over stdio. Connect Claude Desktop, Cursor, Minis, or Windsurf directly to your Ableton Live session:

Add to `claude_desktop_config.json` (or Cursor MCP settings):

```json
{
  "mcpServers": {
    "ableton-agent": {
      "command": "ableton-agent",
      "args": ["mcp"]
    }
  }
}
```

**Exposed MCP Tools:**
- `ableton_plan_and_run`: natural language music production prompt -> executes in Live
- `ableton_send_command`: execute raw Live actions (play, stop, mute, add_notes...)
- `ableton_describe_set`: live inspection of tracks, devices, clips, and tempo
- `ableton_generate_groove`: music-theory chords & Euclidean syncopated rhythms with velocity humanization
- `ableton_get_status`: inspect active model and UDP bridge config

## Music Theory & Humanized Groove Engine 🎼

No more robotic velocity-100 MIDI! The built-in music theory engine adds:
- **Groove Dynamics**: Humanized velocity curves (accented downbeats, ghost offbeats) and micro-timing jitter.
- **Chord Progressions**: Generates full chords (min7, maj7, min9, dim, sus4) across all root keys.
- **Euclidean Rhythm Generator**: Algorithmic syncopated rhythms (Tresillo 3/8, Afro/House 5/16, etc.).

## Any model — no lock-in

| Provider   | `LLM_BASE_URL`                      | `LLM_MODEL` (example)            |
|------------|-------------------------------------|----------------------------------|
| Ollama 🆓  | `http://localhost:11434/v1`         | `qwen2.5:14b`, `llama3.1`        |
| LM Studio 🆓| `http://localhost:1234/v1`         | `local-model`                    |
| DeepSeek   | `https://api.deepseek.com/v1`       | `deepseek-chat`                  |
| Groq       | `https://api.groq.com/openai/v1`    | `llama-3.3-70b-versatile`        |
| OpenRouter | `https://openrouter.ai/api/v1`      | any slug                         |
| OpenAI     | *(default, unset)*                  | `gpt-4o` (default)               |

Fully local & free:

```bash
ollama pull qwen2.5:14b
export LLM_BASE_URL="http://localhost:11434/v1"
export LLM_MODEL="qwen2.5:14b"
export OPENAI_API_KEY="ollama"
ableton-agent run "make a tech house track at 126 BPM"
```

## Remote Control over Network (LAN)

Control Ableton on your Mac/Windows music rig from a separate Linux, server, or mobile terminal:
- On Ableton machine: set `ABLETON_BRIDGE_HOST="0.0.0.0"` before launching Live.
- On client machine: `export ABLETON_AGENT_HOST="192.168.1.50"` and run `ableton-agent`.

## What the LLM can do in Live

18+ actions: create MIDI/audio/return tracks · load samples from your library
(fuzzy file-name search) · write MIDI clips (pitch/start/length/velocity) ·
mix (volume, pan, mute, solo, sends to buses) · load built-in devices
(Reverb, Delay, Glue Compressor...) & set their params · arrangement
automation points · transport (play/stop/BPM) · inspect the set.

Sample library roots: configurable via `ABLETON_SAMPLE_ROOTS` (default `~/Samples` and `~/Music/Samples`).

## Development & CI

Every push runs the build workflow: syntax checks, CLI smoke tests on
Python 3.9–3.12, and sdist/wheel builds. Tag a release to publish the
wheel as a GitHub Release:

```bash
git tag v0.2.0 && git push --tags
```

## Troubleshooting

- **Nothing happens in Live** → check `Log.txt`; everything is logged with
  the `ChatGPTBridge:` prefix.
- **`load_sample` only logs a path** → `insert_file` needs Live 12; on older
  versions drag the found file in.
- **Model replies with prose** → use ≥14B local models (e.g. `qwen2.5:14b`);
  the agent retries and extracts JSON from fences automatically.
