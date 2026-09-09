# ableton-agent 🎹🤖

Control **Ableton Live 11/12 with any LLM** — an opencode-style CLI for
AI-driven music production. Model-agnostic: OpenAI, Ollama, LM Studio,
DeepSeek, Groq, OpenRouter, or any OpenAI-compatible endpoint.

```
you:  "make a tech house track at 126 BPM"
      -> LLM builds a JSON command plan
      -> ableton-agent streams it over UDP
      -> ChatGPTBridge Remote Script executes it inside Ableton
```

## Install

```bash
pip install git+https://github.com/HELBOYCODER/ableton-agent.git
# or from a release wheel:
pip install ableton_agent-0.1.0-py3-none-any.whl

# install the Ableton Remote Script (auto-detects your Live version):
ableton-agent install
# then: restart Ableton > Preferences > Link/Tempo/MIDI
#       > Control Surface = ChatGPTBridge
```

## CLI (opencode-style)

```bash
ableton-agent run "make a tech house track at 126 BPM, intro build drop outro"
ableton-agent run --dry-run "lo-fi beat at 82 BPM"   # print plan, don't touch Live

ableton-agent chat          # interactive session; ':dry' toggle, ':config', 'exit'

ableton-agent send play                       # raw command, no LLM
ableton-agent send set_tempo '{"bpm": 126}'
ableton-agent send describe_set               # dump the current set to Log.txt

ableton-agent config        # show active model / endpoint
ableton-agent --version
```

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

## What the LLM can do in Live

18 actions: create MIDI/audio/return tracks · load samples from your library
(fuzzy file-name search) · write MIDI clips (pitch/start/length/velocity) ·
mix (volume, pan, mute, solo, sends to buses) · load built-in devices
(Reverb, Delay, Glue Compressor...) & set their params · arrangement
automation points · transport (play/stop/BPM) · inspect the set.

Full list: see `SYSTEM_PROMPT` in `src/ableton_agent/core.py`.
Sample library root: edit `SAMPLE_ROOTS` in the installed
`ChatGPTBridge/__init__.py` (default `~/Samples`).

## Repo layout

```
src/ableton_agent/
  cli.py                                # the CLI (argparse, opencode-style)
  core.py                               # LLM planning + UDP bridge
  remote_script/ChatGPTBridge/__init__.py   # runs inside Ableton
.github/workflows/build.yml             # CI: test matrix + build + release
```

## Development / CI

Every push runs the build workflow: syntax checks, CLI smoke tests on
Python 3.9–3.12, and sdist/wheel builds. Tag a release to publish the
wheel as a GitHub Release:

```bash
git tag v0.1.0 && git push --tags
```

## Troubleshooting

- **Nothing happens in Live** → check `Log.txt`; everything is logged with
  the `ChatGPTBridge:` prefix.
- **`load_sample` only logs a path** → `insert_file` needs Live 12; on older
  versions drag the found file in.
- **Model replies with prose** → use ≥14B local models (e.g. `qwen2.5:14b`);
  the agent retries and extracts JSON from fences automatically.
