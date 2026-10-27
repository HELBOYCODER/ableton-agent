import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import os from "node:os";
import readline from "node:readline";
import { z } from "zod";

import { LiveClient } from "../../bridge/src/live-client";
import { TOOLS } from "../../bridge/src/registry";
import { VERSION, cleanParams, explainError, runStdioBridge } from "../../bridge/src/server";
import {
  copyScript,
  registerClaude,
  registerCodex,
  status as installStatus,
  unregisterClaude,
  unregisterCodex,
  writeProjectMcpConfig,
} from "../../installer/src/lib";
import { Assistant, AssistantEvent, listModels } from "./assistant";
import { PRESETS, loadSettings, presetById, resolveApiKey, saveSettings, updateSettings } from "./config";
import { REMOTE_SCRIPT } from "./generated/remote-script";
import { createAppServer } from "./server";

const HELP = `hellboy ${VERSION} - drive Ableton Live from the terminal or the web

Live
  hellboy status                     Live connection and install state
  hellboy play | stop | undo | redo
  hellboy tempo <bpm>
  hellboy tools [filter]             list the ${TOOLS.length} tools
  hellboy call <tool> [key=value ...] [--json '{...}']
                                     run any tool, e.g.
                                     hellboy call notes_chords track=0 slot=0 root=A scale=minor progression=[1,6,3,7]
  hellboy chat ["message"]           the assistant (no message: interactive)

Web
  hellboy serve [--port 7777] [--lan] [--token <secret>]
                                     web control panel without a window; --lan lets
                                     phones and other computers on your network in

Setup
  hellboy install | uninstall        the Live script
  hellboy connect claude|codex       register the MCP bridge with an agent
  hellboy connect project <folder>   write <folder>/.mcp.json
  hellboy config                     show the assistant's provider, model and key
  hellboy config --provider <id> [--base-url URL] [--model M] [--key K] [--effort low|medium|high]
                                     providers: ${PRESETS.map((p) => p.id).join(", ")}
  hellboy models                     list the models your provider offers
  hellboy mcp                        speak MCP on stdio (for agents)

Remote: add --server http://host:7777 --token <secret> (or HELLBOY_SERVER /
HELLBOY_TOKEN) to send status, call, chat and the shortcuts to a machine
running "hellboy serve".`;

// ------------------------------------------------------------------ arguments
interface Args {
  positional: string[];
  flags: Record<string, string | true>;
}

function parseArgs(argv: string[]): Args {
  const positional: string[] = [];
  const flags: Record<string, string | true> = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith("--")) {
      const [key, inline] = arg.slice(2).split("=", 2);
      if (inline !== undefined) flags[key] = inline;
      else if (argv[i + 1] !== undefined && !argv[i + 1].startsWith("--")) flags[key] = argv[++i];
      else flags[key] = true;
    } else positional.push(arg);
  }
  return { positional, flags };
}

/** key=value pairs -> params; values are JSON when they parse as JSON (numbers, true, [1,2], {...}). */
export function parseParams(pairs: string[], json?: string): Record<string, unknown> {
  const params: Record<string, unknown> = json ? JSON.parse(json) : {};
  for (const pair of pairs) {
    const cut = pair.indexOf("=");
    if (cut < 1) throw new Error(`expected key=value, got "${pair}"`);
    const raw = pair.slice(cut + 1);
    let value: unknown = raw;
    try {
      value = JSON.parse(raw);
    } catch {
      value = raw; // plain strings like root=A
    }
    params[pair.slice(0, cut)] = value;
  }
  return params;
}

class CliError extends Error {}

// ------------------------------------------------------------------ backends
interface Backend {
  call(method: string, params: Record<string, unknown>): Promise<unknown>;
  status(): Promise<any>;
  chat(message: string, conversation: string, emit: (event: AssistantEvent) => void): Promise<void>;
  close(): void;
}

const SCHEMAS = new Map(TOOLS.map((tool) => [tool.method, z.object(tool.shape)]));

function validate(method: string, params: Record<string, unknown>): Record<string, unknown> {
  const schema = SCHEMAS.get(method);
  if (!schema) throw new CliError(`unknown tool "${method}" - see: hellboy tools`);
  const parsed = schema.safeParse(params);
  if (!parsed.success) {
    throw new CliError(parsed.error.issues.map((i) => `${i.path.join(".") || "params"}: ${i.message}`).join("\n"));
  }
  return cleanParams(parsed.data as Record<string, unknown>);
}

function localBackend(): Backend {
  const live = new LiveClient(undefined, undefined, 15000);
  const assistant = new Assistant(live, loadSettings);
  return {
    async call(method, params) {
      try {
        return await live.call(method, validate(method, params));
      } catch (error) {
        if (error instanceof CliError) throw error;
        throw new CliError(explainError((error as Error).message));
      }
    },
    async status() {
      let liveInfo: any;
      try {
        liveInfo = { connected: true, info: await live.call("hello", { client: "cli", version: VERSION }) };
      } catch (error) {
        liveInfo = { connected: false, error: explainError((error as Error).message) };
      }
      return { app: { version: VERSION }, live: liveInfo, install: installStatus() };
    },
    async chat(message, conversation, emit) {
      await assistant.run(conversation, message, emit, new AbortController().signal);
    },
    close: () => live.close(),
  };
}

function remoteBackend(server: string, token: string): Backend {
  const base = new URL(server);
  const client = base.protocol === "https:" ? https : http;
  function request(method: string, path: string, body?: unknown, onChunk?: (text: string) => void): Promise<any> {
    return new Promise((resolve, reject) => {
      const req = client.request(new URL(path, base), {
        method,
        headers: { "content-type": "application/json", "x-hellboy-token": token },
      }, (res) => {
        let data = "";
        res.setEncoding("utf8");
        res.on("data", (chunk: string) => (onChunk ? onChunk(chunk) : (data += chunk)));
        res.on("end", () => {
          if (onChunk) return resolve(null);
          let json: any = null;
          try {
            json = JSON.parse(data);
          } catch {
            /* not JSON */
          }
          if ((res.statusCode || 500) >= 400) reject(new CliError(json?.error || `HTTP ${res.statusCode} from ${server}`));
          else resolve(json);
        });
      });
      req.on("error", (error) => reject(new CliError(`cannot reach ${server}: ${error.message}`)));
      if (body !== undefined) req.write(JSON.stringify(body));
      req.end();
    });
  }
  return {
    async call(method, params) {
      const reply = await request("POST", "/api/call", { method, params: validate(method, params) });
      if (!reply.ok) throw new CliError(reply.error);
      return reply.result;
    },
    status: () => request("GET", "/api/status"),
    async chat(message, conversation, emit) {
      let buffer = "";
      await request("POST", "/api/chat", { conversation, message }, (chunk) => {
        buffer += chunk;
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) {
          const line = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          if (line.startsWith("data: ")) emit(JSON.parse(line.slice(6)));
        }
      });
    },
    close: () => undefined,
  };
}

// ------------------------------------------------------------------ output
const tty = process.stdout.isTTY;
const color = (code: number) => (text: string) => (tty ? `\u001b[${code}m${text}\u001b[0m` : text);
const dim = color(2);
const red = color(31);
const green = color(32);

function print(value: unknown): void {
  process.stdout.write(`${typeof value === "string" ? value : JSON.stringify(value, null, 2)}\n`);
}

function chatPrinter(): (event: AssistantEvent) => void {
  let midLine = false;
  return (event) => {
    if (event.type === "text") {
      process.stdout.write(event.text);
      midLine = !event.text.endsWith("\n");
      return;
    }
    if (midLine) process.stdout.write("\n");
    midLine = false;
    if (event.type === "tool") process.stdout.write(dim(`  > ${event.name} ${JSON.stringify(event.input)}\n`));
    else if (event.type === "tool_result") process.stdout.write(event.ok ? dim(`    ${green("ok")} ${event.summary}\n`) : `    ${red("x")} ${event.summary}\n`);
    else if (event.type === "notice") process.stdout.write(`${event.text}\n`);
    else if (event.type === "error") process.stdout.write(`${red(event.text)}\n`);
  };
}

function lanAddresses(): string[] {
  return Object.values(os.networkInterfaces())
    .flat()
    .filter((net): net is os.NetworkInterfaceInfo => Boolean(net && net.family === "IPv4" && !net.internal))
    .map((net) => net.address);
}

// ------------------------------------------------------------------ commands
async function serve(flags: Args["flags"]): Promise<void> {
  const lan = Boolean(flags.lan);
  const port = Number(flags.port || process.env.HELLBOY_APP_PORT || 7777);
  const token = typeof flags.token === "string" ? flags.token : process.env.HELLBOY_TOKEN;
  if (token !== undefined && token.length < 12) throw new CliError("--token must be at least 12 characters");
  const live = new LiveClient(undefined, undefined, 15000);
  const app = createAppServer({
    live,
    bridge: { command: process.execPath, args: (process as any).pkg ? ["mcp"] : [process.argv[1], "mcp"] },
    onActivity: () => undefined,
    onQuit: () => process.exit(0),
    lan,
    token,
  });
  const bound = await app.listen(port, lan ? "0.0.0.0" : "127.0.0.1");
  const hosts = ["127.0.0.1", ...(lan ? lanAddresses() : [])];
  print(`Hellboy ${VERSION} web panel - open in a browser:`);
  for (const host of hosts) print(`  http://${host}:${bound}/?t=${app.token}`);
  print(dim(`token: ${app.token}`));
  if (lan) print(dim("LAN mode: anyone with this link can control Live. Ctrl+C to stop."));
  else print(dim("Only this computer can connect (add --lan for phones/other computers). Ctrl+C to stop."));
  const stop = () => {
    live.close();
    process.exit(0);
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
  await new Promise(() => undefined); // run until stopped
}

async function chat(backend: Backend, message: string | undefined): Promise<void> {
  const conversation = `cli-${process.pid}`;
  if (message) {
    await backend.chat(message, conversation, chatPrinter());
    return;
  }
  print(dim("Hellboy assistant - type a request, empty line or Ctrl+D to quit."));
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: "hellboy> " });
  rl.prompt();
  for await (const line of rl) {
    if (!line.trim()) break;
    await backend.chat(line, conversation, chatPrinter());
    process.stdout.write("\n");
    rl.prompt();
  }
  rl.close();
}

async function connect(target: string | undefined, folder: string | undefined): Promise<void> {
  const bridge = (process as any).pkg
    ? { command: process.execPath, args: ["mcp"] }
    : { command: process.execPath, args: [process.argv[1], "mcp"] };
  if (target === "claude") print(registerClaude(bridge) || red("Claude Code (`claude`) not found"));
  else if (target === "codex") print(registerCodex(bridge) || red("Codex is not set up (~/.codex missing)"));
  else if (target === "project") {
    if (!folder) throw new CliError("usage: hellboy connect project <folder>");
    print(writeProjectMcpConfig(folder, bridge));
  } else if (target === "remove") {
    print({ claude: unregisterClaude(), codex: unregisterCodex() });
  } else throw new CliError("usage: hellboy connect claude|codex|project <folder>|remove");
}

function config(flags: Args["flags"]): void {
  const str = (name: string) => (typeof flags[name] === "string" ? (flags[name] as string) : undefined);
  let settings = loadSettings();
  try {
    settings = updateSettings(settings, {
      preset: str("provider"),
      baseUrl: str("base-url"),
      model: str("model"),
      apiKey: str("key"),
      clearKey: Boolean(flags["clear-key"]),
      effort: str("effort"),
    });
  } catch (error) {
    throw new CliError((error as Error).message);
  }
  saveSettings(settings);
  const key = resolveApiKey(settings);
  print({
    provider: `${settings.preset} (${presetById(settings.preset).label})`,
    protocol: settings.provider,
    baseUrl: settings.baseUrl || "official endpoint",
    model: settings.model || "(none - see: hellboy models)",
    effort: settings.provider === "anthropic" && !settings.baseUrl ? settings.effort : undefined,
    key: key.key ? `${key.key.slice(0, 7)}...${key.key.slice(-4)} (${key.source})` : null,
  });
}

function statusText(s: any): string {
  const live = s.live.connected
    ? `${green("connected")} - Live ${s.live.info?.live_version || "?"}, script ${s.live.info?.version || "1.0"}${s.live.info?.osc_port ? `, OSC :${s.live.info.osc_port}` : ""}`
    : `${red("not connected")} - ${s.live.error}`;
  const lines = [`Hellboy ${s.app.version}`, `Live:   ${live}`];
  if (s.install) {
    lines.push(`Script: ${s.install.scriptInstalled ? `installed ${s.install.installedVersion}` : red("not installed (hellboy install)")}`);
    lines.push(`Folder: ${s.install.scriptPath}`);
  }
  return lines.join("\n");
}

const SHORTCUTS: Record<string, (args: string[]) => [string, Record<string, unknown>]> = {
  play: () => ["transport_play", {}],
  stop: () => ["transport_stop", {}],
  undo: () => ["session_undo", {}],
  redo: () => ["session_redo", {}],
  tempo: ([bpm]) => {
    if (!bpm) throw new CliError("usage: hellboy tempo <bpm>");
    return ["session_set_tempo", { tempo: Number(bpm) }];
  },
};

export async function runCli(argv: string[]): Promise<void> {
  const { positional, flags } = parseArgs(argv);
  const [command, ...rest] = positional;
  if (command === "version" || flags.version) return print(VERSION);
  if (!command || flags.help || command === "help") return print(HELP);
  if (command === "mcp") return runStdioBridge();
  if (command === "serve") return serve(flags);
  if (command === "install") return print({ installed: copyScript({ files: REMOTE_SCRIPT }) });
  if (command === "uninstall") {
    const current = installStatus();
    fs.rmSync(current.scriptPath, { recursive: true, force: true });
    return print({ removed: current.scriptPath });
  }
  if (command === "connect") return connect(rest[0], rest[1]);
  if (command === "config") return config(flags);
  if (command === "models") {
    try {
      for (const id of await listModels(loadSettings())) print(id);
    } catch (error) {
      throw new CliError((error as Error).message);
    }
    return;
  }
  if (command === "tools") {
    const filter = (rest[0] || "").toLowerCase();
    for (const tool of TOOLS) {
      if (filter && !tool.name.includes(filter) && !tool.description.toLowerCase().includes(filter)) continue;
      const params = Object.entries(tool.shape).map(([k, s]) => (s.isOptional() ? `[${k}]` : k)).join(" ");
      print(`${tool.name.padEnd(30)} ${dim(params)}\n${"".padEnd(30)} ${tool.description}`);
    }
    return;
  }

  const server = (typeof flags.server === "string" && flags.server) || process.env.HELLBOY_SERVER;
  const token = (typeof flags.token === "string" && flags.token) || process.env.HELLBOY_TOKEN || "";
  if (server && !token) throw new CliError("--server needs --token (printed by hellboy serve)");
  const backend = server ? remoteBackend(server, token) : localBackend();
  try {
    if (command === "status") {
      const s = await backend.status();
      return print(flags.json ? s : statusText(s));
    }
    if (command === "chat") return await chat(backend, rest.join(" ") || undefined);
    if (command === "call") {
      const [method, ...pairs] = rest;
      if (!method) throw new CliError("usage: hellboy call <tool> [key=value ...]");
      return print(await backend.call(method, parseParams(pairs, typeof flags.json === "string" ? flags.json : undefined)));
    }
    const shortcut = SHORTCUTS[command];
    if (shortcut) {
      const [method, params] = shortcut(rest);
      return print(await backend.call(method, params));
    }
    throw new CliError(`unknown command "${command}" - see: hellboy help`);
  } finally {
    backend.close();
  }
}

if (require.main === module) {
  // `hellboy tools | head` closes the pipe early; that is not an error
  process.stdout.on("error", (error: NodeJS.ErrnoException) => {
    if (error.code === "EPIPE") process.exit(0);
    throw error;
  });
  runCli(process.argv.slice(2)).then(
    () => {
      // serve and mcp keep running on their own; everything else is done
      const command = process.argv.slice(2).find((a) => !a.startsWith("--"));
      if (command !== "serve" && command !== "mcp") process.exit(0);
    },
    (error) => {
      process.stderr.write(`${red("error:")} ${error instanceof CliError ? error.message : (error as Error).stack || error}\n`);
      process.exit(1);
    },
  );
}
