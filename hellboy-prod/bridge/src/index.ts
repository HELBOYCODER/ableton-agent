import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { live } from "./live-client";
import { TOOLS } from "./registry";

const server = new McpServer(
  {
    name: "hellboy",
    version: "1.1.0",
  },
  {
    instructions:
      "Hellboy Prod drives a running Ableton Live set. Start with session_state to learn " +
      "track, slot and scene indices (0-based; negative counts from the end). Every call is " +
      "one undo step in Live (session_undo reverts it). Browser loads go to the selected " +
      "track. For harmony use notes_detect_key, then notes_chords / notes_scale_fit / " +
      "notes_arpeggiate; for groove use notes_swing presets. mix_balance needs the " +
      "transport playing.",
  },
);

function log(message: string): void {
  process.stderr.write(`[hellboy] ${message}\n`);
}

function asText(payload: unknown): { content: { type: "text"; text: string }[] } {
  return { content: [{ type: "text", text: JSON.stringify(payload, null, 2) }] };
}

for (const definition of TOOLS) {
  server.tool(
    definition.name,
    definition.description,
    definition.shape as any,
    async (args: Record<string, unknown>) => {
      const params: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(args || {})) {
        if (value !== undefined && value !== null) params[key] = value;
      }
      try {
        const result = await live.call(definition.method, params);
        return asText(result);
      } catch (error) {
        let message = (error as Error).message || String(error);
        if (message.includes("UnknownMethod")) {
          message += " - the remote script in Live is older than this bridge; re-run the installer and restart Live";
        } else if (/ECONNREFUSED|not connected/.test(message)) {
          message += " - open Live and select Hellboy Prod as a Control Surface (Preferences -> Link/MIDI)";
        }
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
    const endpoint = live.endpoint;
    try {
      const info = await live.hello();
      return asText({ connected: true, endpoint, live: info });
    } catch (error) {
      return asText({
        connected: false,
        endpoint,
        hint:
          "Open Ableton Live, enable the Hellboy Prod control surface, " +
          "then drop nothing else - the script listens on 127.0.0.1:" +
          endpoint.split(":")[1],
        error: (error as Error).message,
      });
    }
  },
);

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  log(`ready, target ${live.endpoint}, ${TOOLS.length + 1} tools`);
}

main().catch((error) => {
  log(`fatal: ${(error as Error).message}`);
  process.exit(1);
});

process.on("SIGINT", () => {
  live.close();
  process.exit(0);
});
