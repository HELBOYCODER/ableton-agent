import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** Per-user settings and runtime files live in ~/.hellboy (HELLBOY_HOME overrides). */
export function homeDir(): string {
  return process.env.HELLBOY_HOME || path.join(os.homedir(), ".hellboy");
}

/** Wire protocol the assistant speaks: Anthropic Messages or OpenAI Chat Completions. */
export const PROVIDERS = ["anthropic", "openai"] as const;
export type Provider = (typeof PROVIDERS)[number];
export const EFFORTS = ["low", "medium", "high"] as const;
export const CLAUDE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"];

export interface Preset {
  id: string;
  label: string;
  provider: Provider;
  /** empty = the provider's official endpoint */
  baseUrl: string;
  /** user types their own base URL */
  custom?: boolean;
  keyRequired: boolean;
  model: string;
  models?: string[];
}

export const PRESETS: Preset[] = [
  { id: "anthropic", label: "Anthropic (Claude)", provider: "anthropic", baseUrl: "", keyRequired: true, model: "claude-opus-5-5", models: CLAUDE_MODELS },
  { id: "anthropic-compatible", label: "Anthropic-compatible (custom URL)", provider: "anthropic", baseUrl: "", custom: true, keyRequired: false, model: "" },
  { id: "openai", label: "OpenAI", provider: "openai", baseUrl: "https://api.openai.com/v1", keyRequired: true, model: "" },
  { id: "openrouter", label: "OpenRouter", provider: "openai", baseUrl: "https://openrouter.ai/api/v1", keyRequired: true, model: "" },
  { id: "deepseek", label: "DeepSeek", provider: "openai", baseUrl: "https://api.deepseek.com/v1", keyRequired: true, model: "" },
  { id: "groq", label: "Groq", provider: "openai", baseUrl: "https://api.groq.com/openai/v1", keyRequired: true, model: "" },
  { id: "ollama", label: "Ollama (local)", provider: "openai", baseUrl: "http://localhost:11434/v1", keyRequired: false, model: "" },
  { id: "lmstudio", label: "LM Studio (local)", provider: "openai", baseUrl: "http://localhost:1234/v1", keyRequired: false, model: "" },
  { id: "openai-compatible", label: "OpenAI-compatible (custom URL)", provider: "openai", baseUrl: "", custom: true, keyRequired: false, model: "" },
];

export function presetById(id: string | undefined): Preset {
  return PRESETS.find((preset) => preset.id === id) || PRESETS[0];
}

export interface Settings {
  preset: string;
  provider: Provider;
  /** "" = official Anthropic endpoint; otherwise the API root, e.g. https://openrouter.ai/api/v1 */
  baseUrl: string;
  model: string;
  apiKey?: string;
  effort: (typeof EFFORTS)[number];
}

const DEFAULTS: Settings = { preset: "anthropic", provider: "anthropic", baseUrl: "", model: "claude-opus-5-5", effort: "medium" };

function settingsFile(): string {
  return path.join(homeDir(), "config.json");
}

/** http(s) URL without a trailing slash, or throws. */
export function normalizeBaseUrl(value: string): string {
  const url = new URL(value.trim());
  if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("base URL must start with http:// or https://");
  return url.toString().replace(/\/+$/, "");
}

export function loadSettings(): Settings {
  try {
    const raw = JSON.parse(fs.readFileSync(settingsFile(), "utf8"));
    // configs from 1.4 and earlier only had apiKey/model/effort (Anthropic)
    const preset = presetById(typeof raw.preset === "string" ? raw.preset : "anthropic");
    const provider: Provider = PROVIDERS.includes(raw.provider) ? raw.provider : preset.provider;
    return {
      preset: preset.id,
      provider,
      baseUrl: typeof raw.baseUrl === "string" ? raw.baseUrl : preset.baseUrl,
      model: typeof raw.model === "string" && raw.model.trim() ? raw.model.trim().slice(0, 200) : preset.model,
      apiKey: typeof raw.apiKey === "string" && raw.apiKey ? raw.apiKey : undefined,
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

/** Switch provider preset: protocol, endpoint and a sensible default model. */
export function applyPreset(settings: Settings, id: string): Settings {
  const preset = presetById(id);
  if (preset.id !== id) throw new Error(`unknown provider preset "${id}" (${PRESETS.map((p) => p.id).join(", ")})`);
  const changed = settings.preset !== preset.id;
  return {
    ...settings,
    preset: preset.id,
    provider: preset.provider,
    baseUrl: preset.custom ? (changed ? "" : settings.baseUrl) : preset.baseUrl,
    model: changed ? preset.model : settings.model,
    // a key for one service must never be sent to another
    apiKey: changed ? undefined : settings.apiKey,
  };
}

/**
 * The key the assistant will use and where it came from. Environment keys are
 * only used for the official endpoints they belong to.
 */
export function resolveApiKey(settings: Settings): { key?: string; source: "settings" | "environment" | "none" } {
  if (settings.apiKey) return { key: settings.apiKey, source: "settings" };
  if (settings.preset === "anthropic" && process.env.ANTHROPIC_API_KEY) return { key: process.env.ANTHROPIC_API_KEY, source: "environment" };
  if (settings.preset === "openai" && process.env.OPENAI_API_KEY) return { key: process.env.OPENAI_API_KEY, source: "environment" };
  return { source: "none" };
}

export interface SettingsChange {
  preset?: string;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  clearKey?: boolean;
  effort?: string;
}

/** Apply a change from the UI or CLI; throws Error with a user-facing message. */
export function updateSettings(current: Settings, change: SettingsChange): Settings {
  let settings = { ...current };
  if (typeof change.preset === "string" && change.preset) settings = applyPreset(settings, change.preset);
  const preset = presetById(settings.preset);
  if (typeof change.baseUrl === "string") {
    if (!preset.custom) throw new Error(`${preset.label} has a fixed URL; choose a "compatible (custom URL)" provider to set one`);
    settings.baseUrl = change.baseUrl.trim() ? normalizeBaseUrl(change.baseUrl) : "";
  }
  if (typeof change.model === "string" && change.model.trim()) {
    const model = change.model.trim();
    if (model.length > 200 || /\s/.test(model)) throw new Error("model names have no spaces and are under 200 characters");
    settings.model = model;
  }
  if (change.clearKey) settings.apiKey = undefined;
  if (typeof change.apiKey === "string" && change.apiKey.trim()) {
    const key = change.apiKey.trim();
    if (settings.preset === "anthropic" && !/^sk-ant-[\w-]{10,}$/.test(key)) {
      throw new Error("that does not look like an Anthropic API key (sk-ant-...)");
    }
    if (key.length > 1000 || /\s/.test(key)) throw new Error("that does not look like an API key");
    settings.apiKey = key;
  }
  if (typeof change.effort === "string" && change.effort) {
    if (!EFFORTS.includes(change.effort as any)) throw new Error(`effort must be one of ${EFFORTS.join(", ")}`);
    settings.effort = change.effort as Settings["effort"];
  }
  return settings;
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
