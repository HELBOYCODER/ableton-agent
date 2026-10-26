import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

/** Installer logic shared by the CLI installer and Hellboy Studio. */

export const SERVER_KEY = "hellboy";
export const SCRIPT_NAME = "HellboyProd";
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
// A pkg-compiled binary runs from a virtual snapshot, so files that ship
// beside it are looked up next to the real executable.
const EXE_DIR = path.dirname(process.execPath);

/** Where the remote script comes from: a folder on disk or embedded files. */
export type ScriptSource = { dir: string } | { files: Record<string, string> };

export interface BridgeCommand {
  command: string;
  args: string[];
}

export function defaultScriptSource(): ScriptSource | null {
  const dir = [
    path.join(PROJECT_ROOT, "remote-script", SCRIPT_NAME),
    path.join(EXE_DIR, SCRIPT_NAME),
    path.join(EXE_DIR, "hellboyprod-remote-script", SCRIPT_NAME),
  ].find((candidate) => fs.existsSync(candidate));
  return dir ? { dir } : null;
}

export function bridgeEntry(): string {
  return path.join(PROJECT_ROOT, "bridge", "dist", "src", "index.js");
}

export function userLibraryCandidates(): string[] {
  const home = os.homedir();
  if (process.platform === "darwin") {
    return [
      path.join(home, "Music", "Ableton", "User Library"),
      path.join(home, "Documents", "Ableton", "User Library"),
    ];
  }
  if (process.platform === "win32") {
    return [
      path.join(home, "Documents", "Ableton", "User Library"),
      path.join(home, "Ableton", "User Library"),
    ];
  }
  return [path.join(home, "Ableton", "User Library")];
}

export function resolveUserLibrary(): string {
  const candidates = userLibraryCandidates();
  return candidates.find((candidate) => fs.existsSync(candidate)) || candidates[0];
}

export function scriptDestination(library = resolveUserLibrary()): string {
  return path.join(library, "Remote Scripts", SCRIPT_NAME);
}

export function copyScript(source: ScriptSource, library = resolveUserLibrary()): string {
  const destination = scriptDestination(library);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.rmSync(destination, { recursive: true, force: true });
  if ("dir" in source) {
    fs.cpSync(source.dir, destination, {
      recursive: true,
      filter: (item) => !item.includes("__pycache__"),
    });
  } else {
    fs.mkdirSync(destination, { recursive: true });
    for (const [name, text] of Object.entries(source.files)) {
      fs.writeFileSync(path.join(destination, path.basename(name)), text, "utf8");
    }
  }
  return destination;
}

/** The command an MCP client should launch: a packaged binary when present. */
export function defaultBridgeCommand(): BridgeCommand {
  const binary =
    process.platform === "win32"
      ? "hellboy-bridge-win-x64.exe"
      : `hellboy-bridge-${process.platform}-${process.arch}`;
  const packaged = [path.join(EXE_DIR, binary), path.join(PROJECT_ROOT, "dist", binary)].find(
    (candidate) => fs.existsSync(candidate),
  );
  if (packaged) return { command: packaged, args: [] };
  return { command: process.execPath, args: [bridgeEntry()] };
}

function port(): string {
  return process.env.HELLBOY_PORT || "8971";
}

export function writeProjectMcpConfig(dir: string, bridge: BridgeCommand): string {
  const file = path.join(dir, ".mcp.json");
  let existing: any = { mcpServers: {} };
  if (fs.existsSync(file)) {
    try {
      existing = JSON.parse(fs.readFileSync(file, "utf8"));
      existing.mcpServers = existing.mcpServers || {};
    } catch {
      existing = { mcpServers: {} };
    }
  }
  existing.mcpServers[SERVER_KEY] = {
    command: bridge.command,
    args: bridge.args,
    env: { HELLBOY_PORT: port() },
  };
  fs.writeFileSync(file, `${JSON.stringify(existing, null, 2)}\n`, "utf8");
  return file;
}

/** Run the `claude` CLI. On Windows it is a .cmd shim, which needs a shell. */
function runClaude(args: string[]): void {
  if (process.platform === "win32") {
    const quoted = args.map((arg) => (/[\s"&|<>^]/.test(arg) ? `"${arg.replace(/"/g, '""')}"` : arg));
    execFileSync("claude", quoted, { stdio: "ignore", shell: true, windowsHide: true });
  } else {
    execFileSync("claude", args, { stdio: "ignore" });
  }
}

let claudeCheck: { at: number; found: boolean } | null = null;

/** Whether the `claude` CLI is installed (cached: starting it is not free). */
export function claudeAvailable(): boolean {
  if (claudeCheck && Date.now() - claudeCheck.at < 60000) return claudeCheck.found;
  let found = false;
  try {
    runClaude(["--version"]);
    found = true;
  } catch {
    found = false;
  }
  claudeCheck = { at: Date.now(), found };
  return found;
}

/** Register for every project of this user (user scope), replacing any old entry. */
export function registerClaude(bridge: BridgeCommand): string | null {
  for (const scope of ["user", "local"]) {
    try {
      runClaude(["mcp", "remove", "-s", scope, SERVER_KEY]);
    } catch {
      /* not registered in this scope */
    }
  }
  try {
    runClaude(["mcp", "add", "-s", "user", "-e", `HELLBOY_PORT=${port()}`, SERVER_KEY, "--",
      bridge.command, ...bridge.args]);
    return "claude mcp add -s user";
  } catch {
    return null;
  }
}

export function unregisterClaude(): boolean {
  let removed = false;
  for (const scope of ["user", "local"]) {
    try {
      runClaude(["mcp", "remove", "-s", scope, SERVER_KEY]);
      removed = true;
    } catch {
      /* ignore */
    }
  }
  return removed;
}

function codexConfig(): string {
  return path.join(os.homedir(), ".codex", "config.toml");
}

export function codexAvailable(): boolean {
  return fs.existsSync(path.dirname(codexConfig()));
}

function withoutCodexEntry(text: string): string {
  return text.replace(/\n?\[mcp_servers\.hellboy(?:\.env)?\][\s\S]*?(?=\n\[(?!mcp_servers\.hellboy)|$)/g, "");
}

export function registerCodex(bridge: BridgeCommand): string | null {
  if (!codexAvailable()) return null;
  const file = codexConfig();
  let text = withoutCodexEntry(fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "");
  text +=
    `\n[mcp_servers.${SERVER_KEY}]\n` +
    `command = ${JSON.stringify(bridge.command)}\n` +
    `args = [${bridge.args.map((arg) => JSON.stringify(arg)).join(", ")}]\n` +
    `\n[mcp_servers.${SERVER_KEY}.env]\nHELLBOY_PORT = ${JSON.stringify(port())}\n`;
  fs.writeFileSync(file, text.trimStart(), "utf8");
  return file;
}

export function unregisterCodex(): boolean {
  const file = codexConfig();
  if (!fs.existsSync(file)) return false;
  const before = fs.readFileSync(file, "utf8");
  const after = withoutCodexEntry(before);
  if (after !== before) fs.writeFileSync(file, after.trimStart(), "utf8");
  return after !== before;
}

export interface InstallStatus {
  platform: string;
  userLibrary: string;
  userLibraryExists: boolean;
  scriptPath: string;
  scriptInstalled: boolean;
  installedVersion: string | null;
  claude: boolean;
  codex: boolean;
}

export function status(): InstallStatus {
  const library = resolveUserLibrary();
  const scriptPath = scriptDestination(library);
  let installedVersion: string | null = null;
  try {
    const init = fs.readFileSync(path.join(scriptPath, "__init__.py"), "utf8");
    installedVersion = /SCRIPT_VERSION = "([^"]+)"/.exec(init)?.[1] || "1.0";
  } catch {
    installedVersion = null;
  }
  return {
    platform: `${process.platform} ${process.arch}`,
    userLibrary: library,
    userLibraryExists: fs.existsSync(library),
    scriptPath,
    scriptInstalled: fs.existsSync(path.join(scriptPath, "__init__.py")),
    installedVersion,
    claude: claudeAvailable(),
    codex: codexAvailable(),
  };
}
