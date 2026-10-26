import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { z } from "zod";

import { LiveClient } from "../../bridge/src/live-client";
import { TOOLS } from "../../bridge/src/registry";
import { VERSION, cleanParams, explainError } from "../../bridge/src/server";
import {
  BridgeCommand,
  copyScript,
  registerClaude,
  registerCodex,
  status as installStatus,
  unregisterClaude,
  unregisterCodex,
  writeProjectMcpConfig,
} from "../../installer/src/lib";
import { Assistant, AssistantEvent } from "./assistant";
import { EFFORTS, MODELS, loadSettings, log, resolveApiKey, saveSettings } from "./config";
import { REMOTE_SCRIPT, SCRIPT_VERSION } from "./generated/remote-script";
import UI from "./ui.html";

const MAX_BODY = 1024 * 1024;
const TOOL_SCHEMAS = new Map(TOOLS.map((tool) => [tool.method, z.object(tool.shape)]));

export interface AppServerOptions {
  live: LiveClient;
  bridge: BridgeCommand;
  onActivity: () => void;
  onQuit: () => void;
}

class HttpError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

function sameToken(a: string | undefined, b: string): boolean {
  if (!a || a.length !== b.length) return false;
  return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
}

async function readJson(req: http.IncomingMessage): Promise<any> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > MAX_BODY) throw new HttpError(413, "request too large");
    chunks.push(chunk as Buffer);
  }
  if (!size) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new HttpError(400, "invalid JSON body");
  }
}

function send(res: http.ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  res.end(body);
}

export function createAppServer(options: AppServerOptions) {
  const token = crypto.randomBytes(24).toString("hex");
  const { live } = options;
  const assistant = new Assistant(live, loadSettings);
  let port = 0;

  async function liveStatus() {
    try {
      const info = await live.call("hello", { client: "studio", version: VERSION });
      return { connected: true, info };
    } catch (error) {
      return { connected: false, error: explainError((error as Error).message) };
    }
  }

  function settingsView() {
    const settings = loadSettings();
    const key = resolveApiKey(settings);
    return {
      hasKey: Boolean(key.key),
      keySource: key.source,
      keyHint: key.key ? `${key.key.slice(0, 7)}...${key.key.slice(-4)}` : null,
      model: settings.model,
      effort: settings.effort,
      models: MODELS,
      efforts: EFFORTS,
    };
  }

  const routes: Record<string, (req: http.IncomingMessage, res: http.ServerResponse) => Promise<unknown>> = {
    "GET /api/status": async () => ({
      app: { version: VERSION, scriptVersion: SCRIPT_VERSION },
      live: await liveStatus(),
      install: installStatus(),
      settings: settingsView(),
      mcp: options.bridge,
    }),

    "GET /api/tools": async () => TOOLS.map(({ name, description, method }) => ({ name, description, method })),

    "POST /api/call": async (req) => {
      const { method, params } = await readJson(req);
      const schema = TOOL_SCHEMAS.get(method);
      if (!schema) throw new HttpError(400, `unknown method ${method}`);
      const parsed = schema.safeParse(params ?? {});
      if (!parsed.success) {
        throw new HttpError(400, parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
      }
      try {
        return { ok: true, result: await live.call(method, cleanParams(parsed.data as Record<string, unknown>)) };
      } catch (error) {
        return { ok: false, error: explainError((error as Error).message) };
      }
    },

    "POST /api/install": async () => {
      const destination = copyScript({ files: REMOTE_SCRIPT });
      log(`installed remote script to ${destination}`);
      return { ok: true, path: destination, install: installStatus() };
    },

    "POST /api/uninstall": async () => {
      const current = installStatus();
      fs.rmSync(current.scriptPath, { recursive: true, force: true });
      return { ok: true, install: installStatus() };
    },

    "POST /api/register": async (req) => {
      const { target, dir, remove } = await readJson(req);
      if (target === "claude") {
        if (remove) return { ok: unregisterClaude() };
        const result = registerClaude(options.bridge);
        if (!result) throw new HttpError(409, "Claude Code (the `claude` command) was not found on this computer");
        return { ok: true, detail: result };
      }
      if (target === "codex") {
        if (remove) return { ok: unregisterCodex() };
        const result = registerCodex(options.bridge);
        if (!result) throw new HttpError(409, "Codex is not set up on this computer (~/.codex is missing)");
        return { ok: true, detail: result };
      }
      if (target === "project") {
        const folder = typeof dir === "string" ? path.resolve(dir.trim()) : "";
        if (!folder || !fs.existsSync(folder) || !fs.statSync(folder).isDirectory()) {
          throw new HttpError(400, "choose an existing project folder");
        }
        return { ok: true, detail: writeProjectMcpConfig(folder, options.bridge) };
      }
      throw new HttpError(400, "target must be claude, codex or project");
    },

    "POST /api/settings": async (req) => {
      const body = await readJson(req);
      const settings = loadSettings();
      if (body.clearKey) settings.apiKey = undefined;
      if (typeof body.apiKey === "string" && body.apiKey.trim()) {
        const key = body.apiKey.trim();
        if (!/^sk-ant-[\w-]{10,}$/.test(key)) throw new HttpError(400, "that does not look like an Anthropic API key (sk-ant-...)");
        settings.apiKey = key;
      }
      if (MODELS.includes(body.model)) settings.model = body.model;
      if (EFFORTS.includes(body.effort)) settings.effort = body.effort;
      saveSettings(settings);
      return settingsView();
    },

    "POST /api/chat/reset": async (req) => {
      const { conversation } = await readJson(req);
      assistant.reset(String(conversation || "main"));
      return { ok: true };
    },

    "POST /api/heartbeat": async () => ({ ok: true }),

    "POST /api/quit": async () => {
      setTimeout(options.onQuit, 100);
      return { ok: true };
    },
  };

  async function chat(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const { conversation, message } = await readJson(req);
    const text = typeof message === "string" ? message.trim() : "";
    if (!text) throw new HttpError(400, "empty message");
    res.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-store",
      connection: "keep-alive",
    });
    const controller = new AbortController();
    res.on("close", () => controller.abort());
    const emit = (event: AssistantEvent) => {
      if (!res.writableEnded) res.write(`data: ${JSON.stringify(event)}\n\n`);
      options.onActivity();
    };
    await assistant.run(String(conversation || "main"), text.slice(0, 20000), emit, controller.signal);
    res.end();
  }

  const server = http.createServer(async (req, res) => {
    try {
      // Only loopback names: blocks DNS-rebinding pages from reaching the API.
      const host = req.headers.host || "";
      if (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) throw new HttpError(403, "bad host");
      const url = new URL(req.url || "/", `http://${host}`);

      if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
        res.writeHead(200, {
          "content-type": "text/html; charset=utf-8",
          "cache-control": "no-store",
          "content-security-policy":
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
          "x-frame-options": "DENY",
          "referrer-policy": "no-referrer",
        });
        res.end(UI);
        return;
      }

      if (!url.pathname.startsWith("/api/")) throw new HttpError(404, "not found");
      const origin = req.headers.origin;
      if (origin && origin !== `http://${host}`) throw new HttpError(403, "cross-origin request");
      if (!sameToken(req.headers["x-hellboy-token"] as string | undefined, token)) {
        throw new HttpError(401, "missing or wrong token - reopen Hellboy Studio");
      }
      options.onActivity();

      if (req.method === "POST" && url.pathname === "/api/chat") {
        await chat(req, res);
        return;
      }
      const route = routes[`${req.method} ${url.pathname}`];
      if (!route) throw new HttpError(404, "not found");
      send(res, 200, await route(req, res));
    } catch (error) {
      const status = error instanceof HttpError ? error.status : 500;
      if (status === 500) log(`error: ${(error as Error).stack || error}`);
      if (!res.headersSent) send(res, status, { error: (error as Error).message });
      else res.end();
    }
  });

  return {
    token,
    server,
    listen(requestedPort = 0): Promise<number> {
      return new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(requestedPort, "127.0.0.1", () => {
          port = (server.address() as { port: number }).port;
          resolve(port);
        });
      });
    },
  };
}
