// End-to-end tests for the hellboy CLI against mock-live, locally and through
// a `hellboy serve --lan` instance (remote mode).
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const CLI = path.join(ROOT, "app", "build", "cli.cjs");
const MOCK = path.join(ROOT, "mock-live", "dist", "index.js");
// HELLBOY_CLI_BIN=dist/hellboy-linux-x64 runs the same tests against a compiled binary
const CMD = process.env.HELLBOY_CLI_BIN ? [path.resolve(process.env.HELLBOY_CLI_BIN)] : [process.execPath, CLI];
const LIVE_PORT = 8996;
const TOKEN = "test-token-0123456789";

let mock, server, serverUrl, home;

function env(extra = {}) {
  return { ...process.env, HOME: home, USERPROFILE: home, HELLBOY_HOME: path.join(home, ".hellboy"), HELLBOY_PORT: String(LIVE_PORT), ...extra };
}

function hellboy(args, extra) {
  const res = spawnSync(CMD[0], [...CMD.slice(1), ...args], { env: env(extra), encoding: "utf8", timeout: 20000 });
  return { code: res.status, out: res.stdout, err: res.stderr };
}

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

before(async () => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), "hellboy-cli-"));
  mock = spawn(process.execPath, [MOCK], { env: env() });
  await waitFor(mock, /mock-live ready/);
  server = spawn(CMD[0], [...CMD.slice(1), "serve", "--lan", "--port", "0", "--token", TOKEN], { env: env() });
  serverUrl = (await waitFor(server, /(http:\/\/127\.0\.0\.1:\d+)\//))[1];
});

after(() => {
  server?.kill();
  mock?.kill();
});

test("help and version", () => {
  assert.match(hellboy(["help"]).out, /hellboy serve/);
  assert.match(hellboy(["--version"]).out, /^\d+\.\d+\.\d+/);
});

test("status reports the Live connection", () => {
  const res = hellboy(["status", "--json"]);
  assert.equal(res.code, 0);
  assert.equal(JSON.parse(res.out).live.connected, true);
});

test("shortcuts and call run tools with key=value parameters", () => {
  assert.equal(hellboy(["tempo", "131"]).code, 0);
  assert.equal(JSON.parse(hellboy(["call", "session_state"]).out).tempo, 131);
  const chords = hellboy(["call", "notes_chords", "track=0", "slot=0", "root=A", "progression=[1,6,3,7]"]);
  assert.equal(chords.code, 0, chords.err);
});

test("bad tools and bad parameters fail with a clear message", () => {
  const unknown = hellboy(["call", "does_not_exist"]);
  assert.equal(unknown.code, 1);
  assert.match(unknown.err, /unknown tool/);
  const bad = hellboy(["call", "session_set_tempo", "tempo=fast"]);
  assert.equal(bad.code, 1);
  assert.match(bad.err, /tempo: Expected number/);
});

test("install writes the remote script", () => {
  const res = hellboy(["install"]);
  assert.equal(res.code, 0, res.err);
  assert.ok(fs.existsSync(path.join(JSON.parse(res.out).installed, "__init__.py")));
});

test("remote mode drives Live through hellboy serve", () => {
  const res = hellboy(["tempo", "99", "--server", serverUrl, "--token", TOKEN]);
  assert.equal(res.code, 0, res.err);
  const state = JSON.parse(hellboy(["call", "session_state", "--server", serverUrl, "--token", TOKEN]).out);
  assert.equal(state.tempo, 99);
  const status = hellboy(["status", "--server", serverUrl, "--token", TOKEN]);
  assert.match(status.out, /connected/);
});

test("remote mode without the right token is refused", () => {
  const res = hellboy(["status", "--server", serverUrl, "--token", "wrong-token-000000000"]);
  assert.equal(res.code, 1);
  assert.match(res.err, /token/);
});

test("serve --lan accepts any host name but still needs the token", async () => {
  const http = require("node:http");
  const port = new URL(serverUrl).port;
  const get = (headers) => new Promise((resolve) => {
    http.get({ host: "127.0.0.1", port, path: "/api/status", headers }, (res) => { res.resume(); resolve(res.statusCode); });
  });
  assert.equal(await get({ host: `studio.local:${port}`, "x-hellboy-token": TOKEN }), 200);
  assert.equal(await get({ host: `studio.local:${port}` }), 401);
});
