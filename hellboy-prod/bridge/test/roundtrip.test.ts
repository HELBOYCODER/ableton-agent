import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { fork, type ChildProcess } from "node:child_process";
import path from "node:path";

import { LiveClient } from "../src/live-client";

const PORT = 8987;

let mock: ChildProcess;
let client: LiveClient;

function waitForLine(child: ChildProcess, timeoutMs = 8000): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("mock did not start")), timeoutMs);
    const onData = (chunk: Buffer) => {
      if (chunk.toString().includes("mock-live ready")) {
        clearTimeout(timer);
        child.stdout?.off("data", onData);
        resolve();
      }
    };
    child.stdout?.on("data", onData);
  });
}

before(async () => {
  const entry = path.resolve(__dirname, "../../../mock-live/dist/index.js");
  mock = fork(entry, [], {
    env: { ...process.env, HELLBOY_PORT: String(PORT) },
    silent: true,
  });
  await waitForLine(mock);
  client = new LiveClient("127.0.0.1", PORT, 5000);
});

after(() => {
  client?.close();
  mock?.kill();
});

test("hello returns product metadata", async () => {
  const info = await client.hello();
  assert.equal(info.product, "Hellboy Prod");
  assert.ok(Array.isArray(info.methods));
  assert.ok(info.methods.includes("session_state"));
});

test("ping answers", async () => {
  assert.equal(await client.ping(), true);
});

test("session_state returns tracks", async () => {
  const state = await client.call("session_state");
  assert.ok(Array.isArray(state.tracks));
  assert.equal(state.tracks.length, 2);
  assert.equal(typeof state.tempo, "number");
});

test("mutating calls round trip", async () => {
  const created = await client.call("track_create_midi", { name: "Bass" });
  assert.equal(created.name, "Bass");

  const listed = await client.call("track_list");
  assert.equal(listed.tracks.length, 3);
});

test("notes round trip", async () => {
  await client.call("clip_create", { track: 0, slot: 0, length: 4 });
  await client.call("notes_set", {
    track: 0,
    slot: 0,
    notes: [
      { pitch: 36, start: 0, dur: 0.5, vel: 100, mute: false },
      { pitch: 43, start: 1, dur: 0.5, vel: 90, mute: false },
    ],
  });
  const read = await client.call("notes_get", { track: 0, slot: 0 });
  assert.equal(read.count, 2);
});

test("unknown method rejects with a useful message", async () => {
  await assert.rejects(() => client.call("does_not_exist"), /UnknownMethod/);
});

test("deferred method resolves", async () => {
  const result = await client.call("mix_balance", { samples: 1, interval: 1 });
  assert.ok(result === null || typeof result === "object");
});
