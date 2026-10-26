#!/usr/bin/env node
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
// A pkg-compiled installer runs from a virtual snapshot, so it looks for the
// remote script and the bridge binary next to its own executable instead.
const EXE_DIR = path.dirname(process.execPath);
const SOURCE_SCRIPT =
  [
    path.join(PROJECT_ROOT, "remote-script", "HellboyProd"),
    path.join(EXE_DIR, "HellboyProd"),
    path.join(EXE_DIR, "hellboyprod-remote-script", "HellboyProd"),
  ].find((candidate) => fs.existsSync(candidate)) ||
  path.join(PROJECT_ROOT, "remote-script", "HellboyProd");
const BRIDGE_ENTRY = path.join(PROJECT_ROOT, "bridge", "dist", "src", "index.js");
const SERVER_KEY = "hellboy";

function info(message: string): void {
  process.stdout.write(`${message}\n`);
}

function fail(message: string): never {
  process.stderr.write(`error: ${message}\n`);
  process.exit(1);
}

function userLibraryCandidates(): string[] {
  const home = os.homedir();
  if (process.platform === "darwin") {
    return [
      path.join(home, "Music", "Ableton", "User Library"),
      path.join(home, "Documents", "Ableton", "User Library"),
    ];
  }
  if (process.platform === "win32") {
    const documents = path.join(home, "Documents");
    return [
      path.join(documents, "Ableton", "User Library"),
      path.join(home, "Ableton", "User Library"),
    ];
  }
  return [path.join(home, "Ableton", "User Library")];
}

function resolveUserLibrary(): string {
  for (const candidate of userLibraryCandidates()) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return userLibraryCandidates()[0];
}

function copyScript(target: string): string {
  const scriptsDir = path.join(target, "Remote Scripts");
  fs.mkdirSync(scriptsDir, { recursive: true });
  const destination = path.join(scriptsDir, "HellboyProd");
  fs.rmSync(destination, { recursive: true, force: true });
  fs.cpSync(SOURCE_SCRIPT, destination, { recursive: true });
  return destination;
}

function bridgeCommand(): { command: string; args: string[] } {
  const binary =
    process.platform === "win32"
      ? "hellboy-bridge-win-x64.exe"
      : `hellboy-bridge-${process.platform}-${process.arch}`;
  const packaged = [path.join(EXE_DIR, binary), path.join(PROJECT_ROOT, "dist", binary)].find(
    (candidate) => fs.existsSync(candidate),
  );
  if (packaged) return { command: packaged, args: [] };
  return { command: process.execPath, args: [BRIDGE_ENTRY] };
}

function writeProjectMcpConfig(cwd: string, command: string, args: string[]): string {
  const file = path.join(cwd, ".mcp.json");
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
    command,
    args,
    env: { HELLBOY_PORT: process.env.HELLBOY_PORT || "8971" },
  };
  fs.writeFileSync(file, `${JSON.stringify(existing, null, 2)}\n`, "utf8");
  return file;
}

function registerClaude(command: string, args: string[]): string | null {
  try {
    execFileSync("claude", ["mcp", "remove", SERVER_KEY], { stdio: "ignore" });
  } catch {
    /* not registered yet */
  }
  try {
    execFileSync("claude", ["mcp", "add", SERVER_KEY, "--", command, ...args], {
      stdio: "ignore",
    });
    return "claude mcp add";
  } catch {
    return null;
  }
}

function registerCodex(command: string, args: string[]): string | null {
  const dir = path.join(os.homedir(), ".codex");
  if (!fs.existsSync(dir)) return null;
  const file = path.join(dir, "config.toml");
  let text = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
  text = text.replace(/\n?\[mcp_servers\.hellboy\][\s\S]*?(?=\n\[|$)/, "");
  const quoted = [command, ...args].map((part) => JSON.stringify(part)).join(", ");
  text += `\n[mcp_servers.${SERVER_KEY}]\ncommand = ${JSON.stringify(command)}\nargs = [${args
    .map((a) => JSON.stringify(a))
    .join(", ")}]\n`;
  fs.writeFileSync(file, text.trimStart(), "utf8");
  return file;
}

function install(): void {
  if (!fs.existsSync(SOURCE_SCRIPT)) fail(`remote script not found at ${SOURCE_SCRIPT}`);

  const library = resolveUserLibrary();
  const scriptPath = copyScript(library);
  info(`remote script -> ${scriptPath}`);

  const { command, args } = bridgeCommand();
  const configPath = writeProjectMcpConfig(process.cwd(), command, args);
  info(`mcp config     -> ${configPath}`);

  const claude = registerClaude(command, args);
  info(`claude code    -> ${claude || "not found (skipped)"}`);
  const codex = registerCodex(command, args);
  info(`codex cli      -> ${codex || "not found (skipped)"}`);

  info("");
  info("Next steps");
  info("  1. Open Ableton Live");
  info("  2. Preferences -> Link / MIDI -> Control Surface -> Hellboy Prod");
  info("  3. In a project folder run your agent and ask for the live set");
  info(`  4. Optional: set HELLBOY_LICENSE for license reporting`);
}

function uninstall(): void {
  const library = resolveUserLibrary();
  const scriptPath = path.join(library, "Remote Scripts", "HellboyProd");
  fs.rmSync(scriptPath, { recursive: true, force: true });
  info(`removed ${scriptPath}`);
  try {
    execFileSync("claude", ["mcp", "remove", SERVER_KEY], { stdio: "ignore" });
    info("removed claude mcp server");
  } catch {
    /* ignore */
  }
}

function status(): void {
  const library = resolveUserLibrary();
  info(`platform        : ${process.platform} ${process.arch}`);
  info(`user library    : ${library}`);
  info(`script installed: ${fs.existsSync(path.join(library, "Remote Scripts", "HellboyProd"))}`);
  info(`bridge entry    : ${BRIDGE_ENTRY} (${fs.existsSync(BRIDGE_ENTRY)})`);
  const { command, args } = bridgeCommand();
  info(`bridge command  : ${command} ${args.join(" ")}`);
}

const command = process.argv[2] || "install";
if (command === "install") install();
else if (command === "uninstall") uninstall();
else if (command === "status") status();
else fail(`unknown command ${command} (install | uninstall | status)`);
