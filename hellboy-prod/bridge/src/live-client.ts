import net from "node:net";

export interface LiveReply {
  id: number;
  ok: boolean;
  result?: any;
  error?: string;
}

/**
 * Newline delimited JSON client for the Hellboy Prod remote script.
 * One socket, request/response matched by incrementing id.
 */
export class LiveClient {
  private socket: net.Socket | null = null;
  private buffer = "";
  private sequence = 0;
  private readonly pending = new Map<number, (reply: LiveReply) => void>();
  private connecting: Promise<void> | null = null;

  constructor(
    private readonly host = process.env.HELLBOY_HOST || "127.0.0.1",
    private readonly port = Number(process.env.HELLBOY_PORT || 8971),
    private readonly timeoutMs = Number(process.env.HELLBOY_TIMEOUT_MS || 30000),
  ) {}

  get endpoint(): string {
    return `${this.host}:${this.port}`;
  }

  get connected(): boolean {
    return Boolean(this.socket && !this.socket.destroyed);
  }

  async connect(): Promise<void> {
    if (this.connected) return;
    if (this.connecting) return this.connecting;

    const attempt = new Promise<void>((resolve, reject) => {
      const socket = net.createConnection({ host: this.host, port: this.port });

      const onError = (error: Error) => {
        socket.removeListener("connect", onConnect);
        socket.destroy();
        reject(error);
      };

      const onConnect = () => {
        socket.removeListener("error", onError);
        socket.on("error", () => undefined);
        socket.on("data", (chunk: Buffer) => this.consume(chunk));
        socket.on("close", () => {
          if (this.socket !== socket) return;
          this.socket = null;
          this.buffer = "";
          // fail in-flight calls now instead of waiting for their timeout
          for (const [id, resolver] of this.pending) {
            this.pending.delete(id);
            resolver({ id, ok: false, error: `connection to ${this.endpoint} closed (is Live still running?)` });
          }
        });
        this.socket = socket;
        resolve();
      };

      socket.once("error", onError);
      socket.once("connect", onConnect);
    });

    this.connecting = attempt;
    try {
      await attempt;
    } finally {
      if (this.connecting === attempt) this.connecting = null;
    }
  }

  private consume(chunk: Buffer): void {
    this.buffer += chunk.toString("utf8");
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      newline = this.buffer.indexOf("\n");
      if (!line.trim()) continue;
      let reply: LiveReply;
      try {
        reply = JSON.parse(line);
      } catch {
        continue;
      }
      const resolver = this.pending.get(reply.id);
      if (resolver) {
        this.pending.delete(reply.id);
        resolver(reply);
      }
    }
  }

  async call<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    await this.connect();
    const socket = this.socket;
    if (!socket) throw new Error(`not connected to ${this.endpoint}`);

    const id = ++this.sequence;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`timeout after ${this.timeoutMs}ms calling ${method}`));
      }, this.timeoutMs);

      this.pending.set(id, (reply) => {
        clearTimeout(timer);
        if (reply.ok) resolve(reply.result as T);
        else reject(new Error(reply.error || `live error in ${method}`));
      });

      try {
        socket.write(`${JSON.stringify({ id, method, params })}\n`);
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error as Error);
      }
    });
  }

  async hello(): Promise<any> {
    return this.call("hello", { client: "bridge", version: "1.3.0" });
  }

  async ping(): Promise<boolean> {
    const reply = await this.call<{ pong: boolean }>("ping");
    return Boolean(reply && reply.pong);
  }

  close(): void {
    if (this.socket) {
      this.socket.destroy();
      this.socket = null;
    }
    this.pending.clear();
  }
}

export const live = new LiveClient();
