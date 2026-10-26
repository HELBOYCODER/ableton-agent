import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";

import { LiveClient } from "../../bridge/src/live-client";
import { TOOLS } from "../../bridge/src/registry";
import { INSTRUCTIONS, cleanParams, explainError } from "../../bridge/src/server";
import { Settings, resolveApiKey } from "./config";

/** Events streamed to the UI while the assistant works. */
export type AssistantEvent =
  | { type: "text"; text: string }
  | { type: "tool"; id: string; name: string; input: unknown }
  | { type: "tool_result"; id: string; ok: boolean; summary: string }
  | { type: "notice"; text: string }
  | { type: "error"; text: string }
  | { type: "done" };

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

function buildTools(): { tools: Anthropic.Beta.BetaTool[]; byName: Map<string, ToolEntry> } {
  const byName = new Map<string, ToolEntry>();
  const tools: Anthropic.Beta.BetaTool[] = TOOLS.map((definition) => {
    const schema = z.object(definition.shape);
    byName.set(definition.name, { method: definition.method, schema });
    const json = zodToJsonSchema(schema as any, { $refStrategy: "none", target: "jsonSchema7" }) as Record<string, unknown>;
    delete json.$schema;
    return {
      name: definition.name,
      description: definition.description,
      input_schema: json as Anthropic.Beta.BetaTool.InputSchema,
      // stream large inputs (note lists) as they are generated; inputs are
      // re-validated with zod below because the server no longer does it
      eager_input_streaming: true,
    };
  });
  return { tools, byName };
}

function summarize(result: unknown): string {
  const text = JSON.stringify(result);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

export class Assistant {
  private readonly conversations = new Map<string, Anthropic.Beta.BetaMessageParam[]>();
  private readonly toolSet = buildTools();
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

  async run(conversation: string, text: string, emit: (event: AssistantEvent) => void, signal: AbortSignal): Promise<void> {
    const settings = this.settings();
    const { key } = resolveApiKey(settings);
    if (!key) {
      emit({ type: "error", text: "Add your Anthropic API key in Setup to use the assistant." });
      emit({ type: "done" });
      return;
    }
    if (this.running.has(conversation)) {
      emit({ type: "error", text: "Still working on the previous message." });
      emit({ type: "done" });
      return;
    }
    this.running.add(conversation);
    const messages = this.conversations.get(conversation) ?? [];
    this.conversations.set(conversation, messages);
    messages.push({ role: "user", content: text });

    try {
      // passing apiKey also stops the SDK from reading ANTHROPIC_AUTH_TOKEN
      await this.loop(new Anthropic({ apiKey: key }), settings, messages, emit, signal);
    } catch (error) {
      emit({ type: "error", text: describeApiError(error) });
      closeDanglingToolUse(messages);
    } finally {
      this.running.delete(conversation);
      emit({ type: "done" });
    }
  }

  private async loop(
    client: Anthropic,
    settings: Settings,
    messages: Anthropic.Beta.BetaMessageParam[],
    emit: (event: AssistantEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    // The refusal fallback ("default" routing) exists for the Opus/Sonnet tier only.
    const fallback = settings.model !== "claude-haiku-5-5";
    let jsonRetries = 0;

    for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
      if (signal.aborted) throw new Error("stopped");
      const stream = client.beta.messages.stream(
        {
          model: settings.model,
          max_tokens: 64000,
          system: SYSTEM,
          tools: this.toolSet.tools,
          messages,
          output_config: { effort: settings.effort },
          cache_control: { type: "ephemeral" },
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
        emit({ type: "tool", id: use.id, name: use.name, input: use.input });
        results.push(await this.execute(use, emit));
      }
      messages.push({ role: "user", content: results });
    }
    emit({ type: "notice", text: `Stopped after ${MAX_TOOL_ROUNDS} tool rounds.` });
  }

  private async execute(
    use: Anthropic.Beta.BetaToolUseBlock,
    emit: (event: AssistantEvent) => void,
  ): Promise<Anthropic.Beta.BetaToolResultBlockParam> {
    const entry = this.toolSet.byName.get(use.name);
    const fail = (summary: string, content: string): Anthropic.Beta.BetaToolResultBlockParam => {
      emit({ type: "tool_result", id: use.id, ok: false, summary });
      return { type: "tool_result", tool_use_id: use.id, is_error: true, content };
    };
    if (!entry) return fail("unknown tool", `unknown tool ${use.name}`);
    const parsed = entry.schema.safeParse(use.input);
    if (!parsed.success) {
      return fail("invalid input", JSON.stringify({ INVALID_INPUT: parsed.error.issues.slice(0, 5) }));
    }
    try {
      const result = await this.live.call(entry.method, cleanParams(parsed.data as Record<string, unknown>));
      emit({ type: "tool_result", id: use.id, ok: true, summary: summarize(result) });
      return { type: "tool_result", tool_use_id: use.id, content: JSON.stringify(result) };
    } catch (error) {
      const message = explainError((error as Error).message || String(error));
      return fail(message, message);
    }
  }
}

/** If a run died between a tool_use and its results, answer the calls so the
 * conversation stays valid (append-only: nothing earlier is rewritten). */
function closeDanglingToolUse(messages: Anthropic.Beta.BetaMessageParam[]): void {
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

function describeApiError(error: unknown): string {
  if (error instanceof Anthropic.AuthenticationError) return "The API key was rejected. Check it in Setup.";
  if (error instanceof Anthropic.PermissionDeniedError) return "This API key cannot use the selected model.";
  if (error instanceof Anthropic.RateLimitError) return "Rate limited by the API - wait a moment and try again.";
  if (error instanceof Anthropic.APIConnectionError) return "Could not reach the Anthropic API - check your internet connection.";
  if (error instanceof Anthropic.APIError) return `API error ${error.status ?? ""}: ${error.message}`;
  return (error as Error).message || String(error);
}
