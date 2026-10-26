import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** Per-user settings and runtime files live in ~/.hellboy (HELLBOY_HOME overrides). */
export function homeDir(): string {
  return process.env.HELLBOY_HOME || path.join(os.homedir(), ".hellboy");
}

export const MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] as const;
export const EFFORTS = ["low", "medium", "high"] as const;

export interface Settings {
  apiKey?: string;
  model: (typeof MODELS)[number];
  effort: (typeof EFFORTS)[number];
}

const DEFAULTS: Settings = { model: "claude-opus-5-5", effort: "medium" };

function settingsFile(): string {
  return path.join(homeDir(), "config.json");
}

export function loadSettings(): Settings {
  try {
    const raw = JSON.parse(fs.readFileSync(settingsFile(), "utf8"));
    return {
      apiKey: typeof raw.apiKey === "string" && raw.apiKey ? raw.apiKey : undefined,
      model: MODELS.includes(raw.model) ? raw.model : DEFAULTS.model,
      effort: EFFORTS.includes(raw.effort) ? raw.effort : DEFAULTS.effort,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

/** Written owner-only: the file can hold an API key. */
export function saveSettings(settings: Settings): void {
  fs.mkdirSync(homeDir(), { recursive: true, mode: 0o700 });
  fs.writeFileSync(settingsFile(), `${JSON.stringify(settings, null, 2)}\n`, { mode: 0o600 });
  try {
    fs.chmodSync(settingsFile(), 0o600);
  } catch {
    /* best effort on Windows */
  }
}

/** The key the assistant will use and where it came from. */
export function resolveApiKey(settings: Settings): { key?: string; source: "settings" | "environment" | "none" } {
  if (settings.apiKey) return { key: settings.apiKey, source: "settings" };
  if (process.env.ANTHROPIC_API_KEY) return { key: process.env.ANTHROPIC_API_KEY, source: "environment" };
  return { source: "none" };
}

export interface InstanceInfo {
  pid: number;
  port: number;
  token: string;
}

function instanceFile(): string {
  return path.join(homeDir(), "app.json");
}

export function readInstance(): InstanceInfo | null {
  try {
    return JSON.parse(fs.readFileSync(instanceFile(), "utf8"));
  } catch {
    return null;
  }
}

export function writeInstance(info: InstanceInfo): void {
  fs.mkdirSync(homeDir(), { recursive: true, mode: 0o700 });
  fs.writeFileSync(instanceFile(), JSON.stringify(info), { mode: 0o600 });
}

export function clearInstance(pid: number): void {
  const current = readInstance();
  if (current && current.pid === pid) fs.rmSync(instanceFile(), { force: true });
}

export function log(message: string): void {
  const line = `${new Date().toISOString()} ${message}\n`;
  try {
    fs.mkdirSync(homeDir(), { recursive: true, mode: 0o700 });
    fs.appendFileSync(path.join(homeDir(), "app.log"), line);
  } catch {
    /* logging must never take the app down */
  }
  try {
    process.stderr.write(`[hellboy-studio] ${message}\n`);
  } catch {
    /* no console (GUI subsystem) */
  }
}
