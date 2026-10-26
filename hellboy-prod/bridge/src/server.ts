import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { LiveClient, live } from "./live-client";
import { TOOLS } from "./registry";

export const VERSION = "1.2.0";

export const INSTRUCTIONS =
  "Hellboy Prod drives a running Ableton Live set. Start with session_state to learn " +
  "track, slot and scene indices (0-based; negative counts from the end). Every call is " +
  "one undo step in Live (session_undo reverts it). Browser loads go to the selected " +
  "track. For harmony use notes_detect_key, then notes_chords / notes_scale_fit / " +
  "notes_arpeggiate; for groove use notes_swing presets. For song structure build " +
  "scenes, then arrangement_from_scenes lays them out with cue points; arrangement_* " +
  "tools edit the timeline (times in beats, bars are 1-based). mix_balance needs the " +
  "transport playing.";

function log(message: string): void {
  process.stderr.write(`[hellboy] ${message}\n`);
}

function asText(payload: unknown): { content: { type: "text"; text: string }[] } {
  return { content: [{ type: "text", text: JSON.stringify(payload, null, 2) }] };
}

/** Append the fix to the errors a user can act on. */
export function explainError(message: string): string {
  if (message.includes("UnknownMethod")) {
    return `${message} - the remote script in Live is older than this bridge; re-run the installer and restart Live`;
  }
  if (/ECONNREFUSED|not connected|closed/.test(message)) {
    return `${message} - open Live and select Hellboy Prod as a Control Surface (Preferences -> Link/MIDI)`;
  }
  return message;
}

/** Drop null/undefined so the remote script applies its own defaults. */
export function cleanParams(args: Record<string, unknown> | undefined): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(args || {})) {
    if (value !== undefined && value !== null) params[key] = value;
  }
  return params;
}

export function createMcpServer(client: LiveClient = live): McpServer {
  const server = new McpServer({ name: "hellboy", version: VERSION }, { instructions: INSTRUCTIONS });

  for (const definition of TOOLS) {
    server.tool(
      definition.name,
      definition.description,
      definition.shape as any,
      async (args: Record<string, unknown>) => {
        try {
          return asText(await client.call(definition.method, cleanParams(args)));
        } catch (error) {
          const message = explainError((error as Error).message || String(error));
          return {
            content: [{ type: "text" as const, text: `hellboy error: ${message}` }],
            isError: true,
          };
        }
      },
    );
  }

  server.tool(
    "bridge_status",
    "Connection status of the bridge and the remote script.",
    {},
    async () => {
      const endpoint = client.endpoint;
      try {
        const info = await client.hello();
        return asText({ connected: true, endpoint, live: info });
      } catch (error) {
        return asText({
          connected: false,
          endpoint,
          hint:
            "Open Ableton Live and select Hellboy Prod as a Control Surface; " +
            "the script listens on 127.0.0.1:" + endpoint.split(":")[1],
          error: (error as Error).message,
        });
      }
    },
  );

  return server;
}

/** Speak MCP on stdio until the client goes away. */
export async function runStdioBridge(client: LiveClient = live): Promise<void> {
  const server = createMcpServer(client);
  await server.connect(new StdioServerTransport());
  log(`ready, target ${client.endpoint}, ${TOOLS.length + 1} tools`);
  process.on("SIGINT", () => {
    client.close();
    process.exit(0);
  });
}
