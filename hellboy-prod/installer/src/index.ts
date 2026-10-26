#!/usr/bin/env node
import fs from "node:fs";
import {
  bridgeEntry,
  copyScript,
  defaultBridgeCommand,
  defaultScriptSource,
  registerClaude,
  registerCodex,
  status as installStatus,
  unregisterClaude,
  unregisterCodex,
  writeProjectMcpConfig,
} from "./lib";

function info(message: string): void {
  process.stdout.write(`${message}\n`);
}

function fail(message: string): never {
  process.stderr.write(`error: ${message}\n`);
  process.exit(1);
}

function install(): void {
  const source = defaultScriptSource();
  if (!source) fail("remote script not found (expected remote-script/HellboyProd or HellboyProd next to the installer)");

  info(`remote script -> ${copyScript(source)}`);

  const bridge = defaultBridgeCommand();
  info(`mcp config     -> ${writeProjectMcpConfig(process.cwd(), bridge)}`);
  info(`claude code    -> ${registerClaude(bridge) || "not found (skipped)"}`);
  info(`codex cli      -> ${registerCodex(bridge) || "not found (skipped)"}`);

  info("");
  info("Next steps");
  info("  1. Open Ableton Live");
  info("  2. Preferences -> Link / MIDI -> Control Surface -> Hellboy Prod");
  info("  3. In a project folder run your agent and ask for the live set");
  info("  4. Optional: set HELLBOY_LICENSE for license reporting");
}

function uninstall(): void {
  const current = installStatus();
  fs.rmSync(current.scriptPath, { recursive: true, force: true });
  info(`removed ${current.scriptPath}`);
  if (unregisterClaude()) info("removed claude mcp server");
  if (unregisterCodex()) info("removed codex mcp server");
}

function status(): void {
  const current = installStatus();
  const bridge = defaultBridgeCommand();
  info(`platform        : ${current.platform}`);
  info(`user library    : ${current.userLibrary}`);
  info(`script installed: ${current.scriptInstalled}${current.installedVersion ? ` (${current.installedVersion})` : ""}`);
  info(`bridge entry    : ${bridgeEntry()}`);
  info(`bridge command  : ${bridge.command} ${bridge.args.join(" ")}`);
  info(`claude code     : ${current.claude ? "found" : "not found"}`);
  info(`codex cli       : ${current.codex ? "found" : "not found"}`);
}

const command = process.argv[2] || "install";
if (command === "install") install();
else if (command === "uninstall") uninstall();
else if (command === "status") status();
else fail(`unknown command ${command} (install | uninstall | status)`);
