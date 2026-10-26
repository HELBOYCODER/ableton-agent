// End-to-end tests for Hellboy Studio: the real bundle against mock-live and a
// fake Anthropic API that speaks the streaming (SSE) protocol.
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const APP = path.join(ROOT, "app", "build", "app.cjs");
// HELLBOY_APP_BIN=dist/hellboy-studio-linux-x64 runs the same tests against a compiled binary
const APP_CMD = process.env.HELLBOY_APP_BIN ? [path.resolve(process.env.HELLBOY_APP_BIN)] : [process.execPath, APP];
const MOCK = path.join(ROOT, "mock-live", "dist", "index.js");
const LIVE_PORT = 8993;

let mock, app, fake, base, token, home;
const anthropicRequests = [];

function waitFor(child, pattern) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`timeout waiting for ${pattern}`)), 10000);
    let seen = "";
    child.stdout.on("data", (chunk) => {
      seen += chunk;
      const match = seen.match(pattern);
      if (match) {
        clearTimeout(timer);
        resolve(match);
      }
    });
  });
}

// ------------------------------------------------------------ fake Anthropic
function sse(events) {
  return events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`).join("");
}

function messageStart(id) {
  return ["message_start", { message: { id, type: "message", role: "assistant", model: "claude-opus-5-5", content: [],
    stop_reason: null, stop_sequence: null, usage: { input_tokens: 10, output_tokens: 1 } } }];
}

function toolUse(index, id, name, input) {
  return [
    ["content_block_start", { index, content_block: { type: "tool_use", id, name, input: {} } }],
    ["content_block_delta", { index, delta: { type: "input_json_delta", partial_json: JSON.stringify(input) } }],
    ["content_block_stop", { index }],
  ];
}

function finish(stopReason) {
  return [["message_delta", { delta: { stop_reason: stopReason, stop_sequence: null }, usage: { output_tokens: 5 } }],
    ["message_stop", {}]];
}

function startFakeAnthropic() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        const parsed = JSON.parse(body);
        anthropicRequests.push({ headers: req.headers, url: req.url, body: parsed });
        res.writeHead(200, { "content-type": "text/event-stream" });
        if (anthropicRequests.length === 1) {
          res.end(sse([
            messageStart("msg_1"),
            ...toolUse(0, "toolu_ok", "session_state", {}),
            ...toolUse(1, "toolu_bad", "session_set_tempo", { tempo: 5 }), // below the schema minimum
            ...finish("tool_use"),
          ]));
        } else {
          res.end(sse([
            messageStart("msg_2"),
            ["content_block_start", { index: 0, content_block: { type: "text", text: "" } }],
            ["content_block_delta", { index: 0, delta: { type: "text_delta", text: "Your set has " } }],
            ["content_block_delta", { index: 0, delta: { type: "text_delta", text: "2 tracks." } }],
            ["content_block_stop", { index: 0 }],
            ...finish("end_turn"),
          ]));
        }
      });
    });
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

// ------------------------------------------------------------------ helpers
function request(method, pathname, { body, headers = {}, auth = true } = {}) {
  const url = new URL(pathname, base);
  return new Promise((resolve, reject) => {
    const req = http.request(url, {
      method,
      headers: {
        "content-type": "application/json",
        ...(auth ? { "x-hellboy-token": token } : {}),
        ...headers,
      },
    }, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => {
        let json = null;
        try { json = JSON.parse(data); } catch { /* html or sse */ }
        resolve({ status: res.statusCode, json, text: data, headers: res.headers });
      });
    });
    req.on("error", reject);
    if (body !== undefined) req.write(JSON.stringify(body));
    req.end();
  });
}

before(async () => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), "hellboy-studio-"));
  mock = spawn(process.execPath, [MOCK], { env: { ...process.env, HELLBOY_PORT: String(LIVE_PORT) } });
  await waitFor(mock, /mock-live ready/);
  fake = await startFakeAnthropic();
  // a PATH with only node on it, so no real `claude` CLI is found or run
  const bin = path.join(home, "bin");
  fs.mkdirSync(bin);
  // (a copy, not a symlink: symlinks need extra rights on Windows)
  fs.copyFileSync(process.execPath, path.join(bin, path.basename(process.execPath)));
  const env = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (!/^(path|anthropic_auth_token)$/i.test(key)) env[key] = value; // Windows spells it "Path"
  }
  app = spawn(APP_CMD[0], APP_CMD.slice(1), {
    env: {
      ...env,
      HOME: home,
      USERPROFILE: home,
      HELLBOY_HOME: path.join(home, ".hellboy"),
      HELLBOY_PORT: String(LIVE_PORT),
      HELLBOY_APP_NO_BROWSER: "1",
      HELLBOY_APP_PRINT_URL: "1",
      HELLBOY_APP_FORCE_NEW: "1",
      ANTHROPIC_API_KEY: "",
      ANTHROPIC_BASE_URL: `http://127.0.0.1:${fake.address().port}`,
      PATH: bin,
    },
  });
  const match = await waitFor(app, /(http:\/\/127\.0\.0\.1:\d+)\/\?t=([0-9a-f]+)/);
  base = match[1];
  token = match[2];
});

after(() => {
  app?.kill();
  mock?.kill();
  fake?.close();
});

// -------------------------------------------------------------------- tests
test("serves the UI with a strict content security policy", async () => {
  const res = await request("GET", "/", { auth: false });
  assert.equal(res.status, 200);
  assert.match(res.text, /<title>Hellboy Studio<\/title>/);
  assert.match(res.headers["content-security-policy"], /default-src 'self'/);
});

test("the API needs the launch token, a loopback host and a same-origin caller", async () => {
  assert.equal((await request("GET", "/api/status", { auth: false })).status, 401);
  assert.equal((await request("GET", "/api/status", { headers: { "x-hellboy-token": "0".repeat(48) }, auth: false })).status, 401);
  assert.equal((await request("GET", "/api/status", { headers: { host: "evil.example:80" } })).status, 403);
  assert.equal((await request("GET", "/api/status", { headers: { origin: "http://evil.example" } })).status, 403);
});

test("status reports Live, install state and settings", async () => {
  const res = await request("GET", "/api/status");
  assert.equal(res.status, 200);
  assert.equal(res.json.live.connected, true);
  assert.equal(res.json.install.scriptInstalled, false);
  assert.equal(res.json.settings.hasKey, false);
  assert.deepEqual(res.json.mcp.args.slice(-1), ["--mcp"]);
});

test("install writes the embedded remote script into the User Library", async () => {
  const res = await request("POST", "/api/install", { body: {} });
  assert.equal(res.status, 200);
  const init = path.join(res.json.path, "__init__.py");
  assert.ok(res.json.path.startsWith(home));
  assert.ok(fs.existsSync(init));
  assert.ok(fs.existsSync(path.join(res.json.path, "hb_arrangement.py")));
  assert.ok(fs.existsSync(path.join(res.json.path, "hb_osc.py")));
  assert.equal(res.json.install.installedVersion, "1.3.0");
});

test("/api/call only runs registry methods with valid parameters", async () => {
  assert.equal((await request("POST", "/api/call", { body: { method: "shutdown" } })).status, 400);
  const bad = await request("POST", "/api/call", { body: { method: "session_set_tempo", params: { tempo: "fast" } } });
  assert.equal(bad.status, 400);
  assert.match(bad.json.error, /tempo/);
  const good = await request("POST", "/api/call", { body: { method: "session_state", params: {} } });
  assert.equal(good.json.ok, true);
  assert.equal(good.json.result.tracks.length, 2);
});

test("register writes a project .mcp.json that launches this app with --mcp", async () => {
  const project = fs.mkdtempSync(path.join(home, "project-"));
  const res = await request("POST", "/api/register", { body: { target: "project", dir: project } });
  assert.equal(res.status, 200);
  const config = JSON.parse(fs.readFileSync(path.join(project, ".mcp.json"), "utf8"));
  assert.deepEqual(config.mcpServers.hellboy.args.slice(-1), ["--mcp"]);
  const missing = await request("POST", "/api/register", { body: { target: "claude" } });
  assert.equal(missing.status, 409);
});

test("settings validate and store the API key owner-only", async () => {
  assert.equal((await request("POST", "/api/settings", { body: { apiKey: "hello" } })).status, 400);
  const res = await request("POST", "/api/settings", { body: { apiKey: "sk-ant-test-0123456789abcdef", model: "claude-opus-5-5" } });
  assert.equal(res.json.hasKey, true);
  assert.equal(res.json.keySource, "settings");
  assert.ok(!JSON.stringify(res.json).includes("0123456789abcdef"), "the key is never sent back");
  const file = path.join(home, ".hellboy", "config.json");
  if (process.platform !== "win32") assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});

test("the assistant runs the tool loop: valid calls reach Live, invalid input is refused", async () => {
  const res = await request("POST", "/api/chat", { body: { conversation: "t1", message: "How many tracks?" } });
  const events = res.text.split("\n\n").filter((l) => l.startsWith("data: ")).map((l) => JSON.parse(l.slice(6)));
  const results = events.filter((e) => e.type === "tool_result");
  assert.deepEqual(results.map((e) => [e.id, e.ok]), [["toolu_ok", true], ["toolu_bad", false]]);
  assert.equal(events.filter((e) => e.type === "text").map((e) => e.text).join(""), "Your set has 2 tracks.");
  assert.equal(events.at(-1).type, "done");

  assert.equal(anthropicRequests.length, 2);
  const [first, second] = anthropicRequests;
  assert.equal(first.body.model, "claude-opus-5-5");
  assert.equal(first.body.stream, true);
  assert.equal(first.body.fallbacks, "default");
  assert.match(first.headers["anthropic-beta"], /server-side-fallback-2026-07-01/);
  assert.deepEqual(first.body.cache_control, { type: "ephemeral" });
  assert.equal(first.body.output_config.effort, "medium");
  assert.ok(first.body.tools.length > 100);
  assert.ok(first.body.tools.every((t) => t.eager_input_streaming === true && t.input_schema.type === "object"));
  assert.equal(first.headers.authorization, "Bearer sk-ant-test-0123456789abcdef");

  const toolResults = second.body.messages.at(-1).content;
  assert.equal(toolResults[0].tool_use_id, "toolu_ok");
  assert.ok(!toolResults[0].is_error);
  assert.equal(toolResults[1].is_error, true);
  assert.match(toolResults[1].content, /INVALID_INPUT/);
});

test("--mcp turns the app binary into the MCP bridge", async () => {
  const child = spawn(APP_CMD[0], [...APP_CMD.slice(1), "--mcp"], { env: { ...process.env, HELLBOY_PORT: String(LIVE_PORT) } });
  const replies = {};
  let buffer = "";
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    let i;
    while ((i = buffer.indexOf("\n")) >= 0) {
      const line = JSON.parse(buffer.slice(0, i));
      buffer = buffer.slice(i + 1);
      replies[line.id] = line;
    }
  });
  const send = (msg) => child.stdin.write(`${JSON.stringify(msg)}\n`);
  send({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "0" } } });
  await new Promise((r) => setTimeout(r, 400));
  send({ jsonrpc: "2.0", method: "notifications/initialized" });
  send({ jsonrpc: "2.0", id: 2, method: "tools/list" });
  await new Promise((r) => setTimeout(r, 600));
  child.kill();
  assert.equal(replies[1].result.serverInfo.name, "hellboy");
  const names = replies[2].result.tools.map((t) => t.name);
  assert.ok(names.includes("arrangement_from_scenes") && names.includes("bridge_status"));
});
