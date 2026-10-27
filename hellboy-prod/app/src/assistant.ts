import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";

import { LiveClient } from "../../bridge/src/live-client";
import { TOOLS } from "../../bridge/src/registry";
import { INSTRUCTIONS, cleanParams, explainError } from "../../bridge/src/server";
import { Settings, presetById, resolveApiKey } from "./config";

/** Events streamed to the UI while the assistant works. */
export type AssistantEvent =
  | { type: "text"; text: string }
  | { type: "tool"; id: string; name: string; input: unknown }
  | { type: "tool_result"; id: string; ok: boolean; summary: string }
  | { type: "notice"; text: string }
  | { type: "error"; text: string }
  | { type: "done" };

type Emit = (event: AssistantEvent) => void;

const SYSTEM = [
  "You are Hellboy, the production assistant inside Hellboy Studio. You work directly in the",
  "user's running Ableton Live set through tools, as a skilled producer and engineer would.",
  "",
  INSTRUCTIONS,
  "",
  "How to work:",
  "- Look before you change: read session_state (and track_brief or notes_get when it matters)",
  "  so indices, names and existing material are right.",
  "- Make the change the user asked for, then say briefly what you did in musical terms",
  "  (key, chords, bars, which track and slot) so they can find it in Live.",
  "- Every tool call is a single undo step; tell the user they can press Undo if they want",
  "  something back. Ask first only before deleting tracks, clips or scenes the user did not",
  "  mention.",
  "- If a tool answers with ok: false and a reason (for example a feature that needs a newer",
  "  Live), explain the reason and offer the closest thing that works.",
  "- Reply in the language the user writes in. Keep replies short; this is a studio, not an essay.",
].join("\n");

const MAX_TOOL_ROUNDS = 40;

interface ToolEntry {
  method: string;
  schema: z.ZodTypeAny;
}

interface ToolSet {
  byName: Map<string, ToolEntry>;
  /** name, description and JSON schema of every tool, shared by both wire formats */
  specs: { name: string; description: string; parameters: Record<string, unknown> }[];
}

function buildTools(): ToolSet {
  const byName = new Map<string, ToolEntry>();
  const specs = TOOLS.map((definition) => {
    const schema = z.object(definition.shape);
    byName.set(definition.name, { method: definition.method, schema });
    const json = zodToJsonSchema(schema as any, { $refStrategy: "none", target: "jsonSchema7" }) as Record<string, unknown>;
    delete json.$schema;
    return { name: definition.name, description: definition.description, parameters: json };
  });
  return { byName, specs };
}

function summarize(result: unknown): string {
  const text = JSON.stringify(result);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

/** Messages of whichever wire format the conversation was started with. */
interface Conversation {
  signature: string;
  messages: any[];
}

export class Assistant {
  private readonly conversations = new Map<string, Conversation>();
  private readonly tools = buildTools();
  private readonly running = new Set<string>();

  constructor(
    private readonly live: LiveClient,
    private readonly settings: () => Settings,
  ) {}

  reset(conversation: string): void {
    this.conversations.delete(conversation);
  }

  busy(conversation: string): boolean {
    return this.running.has(conversation);
  }

  async run(conversation: string, text: string, emit: Emit, signal: AbortSignal): Promise<void> {
    const settings = this.settings();
    const preset = presetById(settings.preset);
    const { key } = resolveApiKey(settings);
    const problem =
      preset.keyRequired && !key
        ? `Add your ${preset.label} API key in Setup to use the assistant.`
        : !settings.model
          ? "Choose a model in Setup (Load models lists what your provider offers)."
          : preset.custom && !settings.baseUrl
            ? "Enter the base URL of your server in Setup."
            : null;
    if (problem) {
      emit({ type: "error", text: problem });
      emit({ type: "done" });
      return;
    }
    if (this.running.has(conversation)) {
      emit({ type: "error", text: "Still working on the previous message." });
      emit({ type: "done" });
      return;
    }
    this.running.add(conversation);

    // a history in one wire format cannot be replayed to another provider
    const signature = `${settings.provider}|${settings.baseUrl}|${settings.model}`;
    let state = this.conversations.get(conversation);
    if (state && state.signature !== signature) {
      emit({ type: "notice", text: "Provider or model changed - starting a fresh conversation." });
      state = undefined;
    }
    if (!state) {
      state = { signature, messages: [] };
      this.conversations.set(conversation, state);
    }

    try {
      if (settings.provider === "openai") await this.openaiLoop(settings, key, state.messages, text, emit, signal);
      else await this.anthropicLoop(settings, key, state.messages, text, emit, signal);
    } catch (error) {
      emit({ type: "error", text: describeError(error) });
      if (settings.provider === "openai") closeDanglingOpenAi(state.messages);
      else closeDanglingAnthropic(state.messages);
    } finally {
      this.running.delete(conversation);
      emit({ type: "done" });
    }
  }

  /** Validate a tool call with the registry's zod schema, then run it in Live. */
  private async execute(id: string, name: string, input: unknown, emit: Emit): Promise<{ ok: boolean; content: string }> {
    emit({ type: "tool", id, name, input });
    const fail = (summary: string, content: string) => {
      emit({ type: "tool_result", id, ok: false, summary });
      return { ok: false, content };
    };
    const entry = this.tools.byName.get(name);
    if (!entry) return fail("unknown tool", `unknown tool ${name}`);
    const parsed = entry.schema.safeParse(input);
    if (!parsed.success) {
      return fail("invalid input", JSON.stringify({ INVALID_INPUT: parsed.error.issues.slice(0, 5) }));
    }
    try {
      const result = await this.live.call(entry.method, cleanParams(parsed.data as Record<string, unknown>));
      emit({ type: "tool_result", id, ok: true, summary: summarize(result) });
      return { ok: true, content: JSON.stringify(result) };
    } catch (error) {
      const message = explainError((error as Error).message || String(error));
      return fail(message, message);
    }
  }

  // ----------------------------------------------------------- Anthropic
  private async anthropicLoop(
    settings: Settings,
    key: string | undefined,
    messages: Anthropic.Beta.BetaMessageParam[],
    text: string,
    emit: Emit,
    signal: AbortSignal,
  ): Promise<void> {
    // The official endpoint gets the full feature set; an Anthropic-compatible
    // server gets the plain Messages API, since extras such as betas, effort
    // or fallbacks are rejected by servers that do not implement them.
    const official = !settings.baseUrl;
    const client = official
      ? new Anthropic({ apiKey: key })
      : new Anthropic({ apiKey: key || "not-needed", baseURL: settings.baseUrl });
    const fallback = official && settings.model !== "claude-haiku-5-5";
    const tools: Anthropic.Beta.BetaTool[] = this.tools.specs.map((spec) => ({
      name: spec.name,
      description: spec.description,
      input_schema: spec.parameters as Anthropic.Beta.BetaTool.InputSchema,
      // stream large inputs (note lists) as generated; inputs are re-validated in execute()
      ...(official ? { eager_input_streaming: true } : {}),
    }));
    messages.push({ role: "user", content: text });
    let jsonRetries = 0;

    for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
      if (signal.aborted) throw new Error("stopped");
      const stream = client.beta.messages.stream(
        {
          model: settings.model,
          max_tokens: official ? 64000 : 8192,
          system: SYSTEM,
          tools,
          messages,
          ...(official ? { output_config: { effort: settings.effort }, cache_control: { type: "ephemeral" as const } } : {}),
          ...(fallback ? { betas: ["server-side-fallback-2026-07-01"], fallbacks: "default" as const } : {}),
        },
        { signal },
      );
      stream.on("text", (delta) => emit({ type: "text", text: delta }));

      let message: Anthropic.Beta.BetaMessage;
      try {
        message = await stream.finalMessage();
        jsonRetries = 0;
      } catch (error) {
        // only an unparseable streamed tool input is retried; API errors propagate
        if (error instanceof Anthropic.APIError || signal.aborted || jsonRetries++ >= 2) throw error;
        continue;
      }

      if (message.stop_reason === "refusal") {
        emit({ type: "notice", text: "The model declined this request." });
        return;
      }
      if (message.stop_reason === "pause_turn") {
        messages.push({ role: "assistant", content: message.content });
        continue;
      }
      const toolUses = message.content.filter(
        (block): block is Anthropic.Beta.BetaToolUseBlock => block.type === "tool_use",
      );
      if (message.stop_reason === "max_tokens" && toolUses.length > 0) {
        throw new Error("a tool input was cut off at max_tokens; try a smaller request");
      }
      // keep the full content (thinking blocks included): history is append-only
      messages.push({ role: "assistant", content: message.content });
      if (toolUses.length === 0) return;

      const results: Anthropic.Beta.BetaToolResultBlockParam[] = [];
      for (const use of toolUses) {
        const result = await this.execute(use.id, use.name, use.input, emit);
        results.push({ type: "tool_result", tool_use_id: use.id, content: result.content, ...(result.ok ? {} : { is_error: true }) });
      }
      messages.push({ role: "user", content: results });
    }
    emit({ type: "notice", text: `Stopped after ${MAX_TOOL_ROUNDS} tool rounds.` });
  }

  // ------------------------------------------------- OpenAI-compatible
  private async openaiLoop(
    settings: Settings,
    key: string | undefined,
    messages: any[],
    text: string,
    emit: Emit,
    signal: AbortSignal,
  ): Promise<void> {
    const tools = this.tools.specs.map((spec) => ({
      type: "function",
      function: { name: spec.name, description: spec.description, parameters: spec.parameters },
    }));
    if (messages.length === 0) messages.push({ role: "system", content: SYSTEM });
    messages.push({ role: "user", content: text });

    for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
      if (signal.aborted) throw new Error("stopped");
      const reply = await streamChatCompletion(settings.baseUrl, key, { model: settings.model, messages, tools }, emit, signal);
      const calls = reply.toolCalls.map((call, index) => ({
        id: call.id || `call_${round}_${index}`,
        type: "function",
        function: { name: call.name, arguments: call.arguments || "{}" },
      }));
      messages.push({ role: "assistant", content: reply.content || null, ...(calls.length ? { tool_calls: calls } : {}) });
      if (calls.length === 0) {
        if (reply.finishReason === "content_filter") emit({ type: "notice", text: "The model declined this request." });
        return;
      }
      for (const call of calls) {
        let input: unknown;
        try {
          input = JSON.parse(call.function.arguments);
        } catch {
          emit({ type: "tool", id: call.id, name: call.function.name, input: call.function.arguments });
          emit({ type: "tool_result", id: call.id, ok: false, summary: "arguments were not valid JSON" });
          messages.push({ role: "tool", tool_call_id: call.id, content: "error: arguments were not valid JSON" });
          continue;
        }
        const result = await this.execute(call.id, call.function.name, input, emit);
        messages.push({ role: "tool", tool_call_id: call.id, content: result.ok ? result.content : `error: ${result.content}` });
      }
    }
    emit({ type: "notice", text: `Stopped after ${MAX_TOOL_ROUNDS} tool rounds.` });
  }
}

interface ChatReply {
  content: string;
  toolCalls: { id?: string; name: string; arguments: string }[];
  finishReason: string | null;
}

class ProviderError extends Error {}

/** POST {base}/chat/completions with stream: true and fold the SSE deltas back together. */
async function streamChatCompletion(
  baseUrl: string,
  key: string | undefined,
  body: Record<string, unknown>,
  emit: Emit,
  signal: AbortSignal,
): Promise<ChatReply> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "text/event-stream",
        ...(key ? { authorization: `Bearer ${key}` } : {}),
      },
      body: JSON.stringify({ ...body, stream: true }),
      signal,
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new ProviderError(`Could not reach ${baseUrl} - is the server running and the URL right? (${(error as Error).message})`);
  }
  if (!res.ok || !res.body) {
    const detail = (await res.text().catch(() => "")).slice(0, 400);
    if (res.status === 401 || res.status === 403) throw new ProviderError(`The provider rejected the API key (${res.status}). Check it in Setup.`);
    if (res.status === 404) throw new ProviderError(`${baseUrl}/chat/completions was not found (404) - check the base URL and model name. ${detail}`);
    if (res.status === 429) throw new ProviderError("Rate limited by the provider - wait a moment and try again.");
    throw new ProviderError(`Provider error ${res.status}: ${detail}`);
  }

  const reply: ChatReply = { content: "", toolCalls: [], finishReason: null };
  const decoder = new TextDecoder();
  let buffer = "";
  const handle = (line: string) => {
    if (!line.startsWith("data:")) return;
    const data = line.slice(5).trim();
    if (!data || data === "[DONE]") return;
    let chunk: any;
    try {
      chunk = JSON.parse(data);
    } catch {
      return;
    }
    if (chunk.error) throw new ProviderError(`Provider error: ${chunk.error.message || JSON.stringify(chunk.error)}`);
    const choice = chunk.choices?.[0];
    if (!choice) return;
    const delta = choice.delta || choice.message || {};
    if (typeof delta.content === "string" && delta.content) {
      reply.content += delta.content;
      emit({ type: "text", text: delta.content });
    }
    for (const call of delta.tool_calls || []) {
      const index = typeof call.index === "number" ? call.index : reply.toolCalls.length;
      const slot = (reply.toolCalls[index] ||= { name: "", arguments: "" });
      if (call.id) slot.id = call.id;
      if (call.function?.name) slot.name += call.function.name;
      if (call.function?.arguments) {
        slot.arguments += typeof call.function.arguments === "string" ? call.function.arguments : JSON.stringify(call.function.arguments);
      }
    }
    if (choice.finish_reason) reply.finishReason = choice.finish_reason;
  };
  for await (const chunk of res.body as any as AsyncIterable<Uint8Array>) {
    buffer += decoder.decode(chunk, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n")) >= 0) {
      handle(buffer.slice(0, cut).trim());
      buffer = buffer.slice(cut + 1);
    }
  }
  handle(buffer.trim());
  reply.toolCalls = reply.toolCalls.filter((call) => call && call.name);
  return reply;
}

/** If a run died between a tool_use and its results, answer the calls so the
 * conversation stays valid (append-only: nothing earlier is rewritten). */
function closeDanglingAnthropic(messages: Anthropic.Beta.BetaMessageParam[]): void {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant" || typeof last.content === "string") return;
  const pending = last.content.filter(
    (block): block is Anthropic.Beta.BetaToolUseBlock => block.type === "tool_use",
  );
  if (pending.length === 0) return;
  messages.push({
    role: "user",
    content: pending.map((block) => ({
      type: "tool_result" as const,
      tool_use_id: block.id,
      is_error: true,
      content: "interrupted before this tool ran",
    })),
  });
}

function closeDanglingOpenAi(messages: any[]): void {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant" || !last.tool_calls) return;
  const answered = new Set(messages.filter((m) => m.role === "tool").map((m) => m.tool_call_id));
  for (const call of last.tool_calls) {
    if (!answered.has(call.id)) messages.push({ role: "tool", tool_call_id: call.id, content: "error: interrupted before this tool ran" });
  }
}

function describeError(error: unknown): string {
  if (error instanceof ProviderError) return error.message;
  if (error instanceof Anthropic.AuthenticationError) return "The API key was rejected. Check it in Setup.";
  if (error instanceof Anthropic.PermissionDeniedError) return "This API key cannot use the selected model.";
  if (error instanceof Anthropic.NotFoundError) return "Model or endpoint not found - check the model name and base URL in Setup.";
  if (error instanceof Anthropic.RateLimitError) return "Rate limited by the API - wait a moment and try again.";
  if (error instanceof Anthropic.APIConnectionError) return "Could not reach the API - check your internet connection or the base URL.";
  if (error instanceof Anthropic.APIError) return `API error ${error.status ?? ""}: ${error.message}`;
  return (error as Error).message || String(error);
}

/** Model ids the configured provider offers (for the Setup picker). */
export async function listModels(settings: Settings): Promise<string[]> {
  const preset = presetById(settings.preset);
  const { key } = resolveApiKey(settings);
  if (settings.provider === "anthropic") {
    const client = settings.baseUrl
      ? new Anthropic({ apiKey: key || "not-needed", baseURL: settings.baseUrl })
      : new Anthropic({ apiKey: key });
    try {
      const ids: string[] = [];
      for await (const model of client.models.list()) ids.push(model.id);
      return ids;
    } catch (error) {
      if (preset.models) return preset.models;
      throw new ProviderError(describeError(error));
    }
  }
  if (!settings.baseUrl) throw new ProviderError("Enter the base URL first.");
  let res: Response;
  try {
    res = await fetch(`${settings.baseUrl}/models`, { headers: key ? { authorization: `Bearer ${key}` } : {} });
  } catch (error) {
    throw new ProviderError(`Could not reach ${settings.baseUrl} (${(error as Error).message})`);
  }
  if (!res.ok) throw new ProviderError(`${settings.baseUrl}/models answered ${res.status}`);
  const body: any = await res.json();
  const list = Array.isArray(body) ? body : body.data || body.models || [];
  return list.map((m: any) => (typeof m === "string" ? m : m.id || m.name)).filter(Boolean).sort();
}
