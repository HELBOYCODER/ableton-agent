import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";

import { LiveClient } from "../../bridge/src/live-client";
import { VERSION, runStdioBridge } from "../../bridge/src/server";
import { BridgeCommand } from "../../installer/src/lib";
import { clearInstance, log, readInstance, writeInstance } from "./config";
import { createAppServer } from "./server";

/** No open UI for this long and the app exits (the UI pings every 15 s). */
const IDLE_MS = Number(process.env.HELLBOY_APP_IDLE_MS || 3 * 60 * 1000);

/** How agents should launch the bridge: this very executable with --mcp. */
function selfBridgeCommand(): BridgeCommand {
  const packaged = Boolean((process as any).pkg);
  if (packaged) return { command: process.execPath, args: ["--mcp"] };
  return { command: process.execPath, args: [path.resolve(process.argv[1]), "--mcp"] };
}

function openBrowser(url: string): void {
  if (process.env.HELLBOY_APP_NO_BROWSER) return;
  const [command, args] =
    process.platform === "darwin"
      ? ["open", [url]]
      : process.platform === "win32"
        ? ["rundll32", ["url.dll,FileProtocolHandler", url]]
        : ["xdg-open", [url]];
  try {
    spawn(command as string, args as string[], { detached: true, stdio: "ignore", windowsHide: true }).unref();
  } catch (error) {
    log(`could not open a browser: ${(error as Error).message}; open ${url}`);
  }
}

function appUrl(port: number, token: string): string {
  return `http://127.0.0.1:${port}/?t=${token}`;
}

/** Ask an already running instance to show itself; true if it answered. */
function pingExisting(): Promise<boolean> {
  const existing = readInstance();
  if (!existing) return Promise.resolve(false);
  return new Promise((resolve) => {
    const req = http.request(
      {
        host: "127.0.0.1",
        port: existing.port,
        path: "/api/heartbeat",
        method: "POST",
        headers: { "x-hellboy-token": existing.token, host: `127.0.0.1:${existing.port}` },
        timeout: 1500,
      },
      (res) => {
        res.resume();
        if (res.statusCode === 200) {
          openBrowser(appUrl(existing.port, existing.token));
          resolve(true);
        } else resolve(false);
      },
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.end();
  });
}

async function startStudio(): Promise<void> {
  if (!process.env.HELLBOY_APP_FORCE_NEW && (await pingExisting())) {
    log("Hellboy Studio is already running - opened it in the browser");
    return;
  }

  let lastActivity = Date.now();
  const live = new LiveClient(undefined, undefined, 15000);
  let shuttingDown = false;
  const quit = () => {
    if (shuttingDown) return;
    shuttingDown = true;
    clearInstance(process.pid);
    live.close();
    log("Hellboy Studio stopped");
    process.exit(0);
  };

  const app = createAppServer({
    live,
    bridge: selfBridgeCommand(),
    onActivity: () => {
      lastActivity = Date.now();
    },
    onQuit: quit,
  });
  const port = await app.listen(Number(process.env.HELLBOY_APP_PORT || 0));
  writeInstance({ pid: process.pid, port, token: app.token });
  const url = appUrl(port, app.token);
  log(`Hellboy Studio ${VERSION} on ${url.replace(app.token, "<token>")}`);
  if (process.env.HELLBOY_APP_PRINT_URL) process.stdout.write(`${url}\n`);
  openBrowser(url);

  setInterval(() => {
    if (Date.now() - lastActivity > IDLE_MS) {
      log("no open window for a while - shutting down");
      quit();
    }
  }, 10000).unref();
  process.on("SIGINT", quit);
  process.on("SIGTERM", quit);
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (args.includes("--version")) {
    process.stdout.write(`${VERSION}\n`);
    return;
  }
  if (args.includes("--mcp")) {
    await runStdioBridge();
    return;
  }
  await startStudio();
}

main().catch((error) => {
  log(`fatal: ${(error as Error).stack || error}`);
  process.exit(1);
});
