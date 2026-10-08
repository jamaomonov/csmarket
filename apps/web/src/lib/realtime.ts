/**
 * The order-updates socket (M4b, ADR-0008): `WS /api/v1/realtime/orders`.
 *
 * On open it sends `{"type":"auth","token":…}` — nothing secret travels in the URL. The
 * server answers with `{"type":"order.changed","number"}` (or `{"type":"sale.updated","number"}`) nudges and a ping every 25 s; a
 * nudge carries no data, the caller re-reads the order. Polling stays the reconciler: the
 * socket only makes a change show sooner.
 *
 * - Reconnects with backoff `min(30 s, 500 ms × 2^attempt)` plus up to 20 % jitter, with a
 *   fresh token each time; the attempt count resets once the server speaks.
 * - Close 4401 (bad or expired token): one token refresh and an immediate reconnect; a
 *   second 4401 before the server speaks backs off like any drop.
 * - 60 s without any frame closes the socket (a dead connection the browser has not
 *   noticed) and reconnects.
 */

export type SocketState = "connecting" | "open" | "closed";

export interface OrderSocketOptions {
  /** `ws(s)://…/api/v1/realtime/orders` (see {@link wsUrl}). */
  url: string;
  /** The current access token; `null` when there is none (try again later). */
  getToken: () => Promise<string | null>;
  /** Re-mint the access token; `true` on success. Called once after a 4401. */
  refreshToken?: () => Promise<boolean>;
  /** An order of the signed-in buyer changed. */
  onChanged: (number: string) => void;
  /** A sale of the signed-in seller changed (`sale.updated`). */
  onSaleChanged?: (number: string) => void;
  onState?: (state: SocketState) => void;
  /** For tests: the WebSocket constructor. */
  WebSocketImpl?: typeof WebSocket;
  /** For tests: the jitter source. */
  random?: () => number;
}

const PATH = "/api/v1/realtime/orders";
const UNAUTHORIZED = 4401;
const SILENCE_MS = 60_000;
const MAX_BACKOFF_MS = 30_000;

/** The socket URL of an API origin: `http` → `ws`, `https` → `wss`. */
export function wsUrl(apiBase: string): string {
  return apiBase.replace(/\/$/, "").replace(/^http/, "ws") + PATH;
}

/** Reconnecting client for order nudges; see the module comment. */
export class OrderSocket {
  private readonly opts: OrderSocketOptions;
  private socket: WebSocket | null = null;
  private attempt = 0;
  private refreshed = false;
  private stopped = true;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private silenceTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: OrderSocketOptions) {
    this.opts = opts;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    this.opts.onState?.("connecting");
    const token = await this.opts.getToken();
    if (this.isStopped()) return; // stop() may have run during the await
    if (token === null) {
      this.retryLater();
      return;
    }
    const Impl = this.opts.WebSocketImpl ?? WebSocket;
    const socket = new Impl(this.opts.url);
    this.socket = socket;
    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({ type: "auth", token }));
      this.armSilence(socket);
      this.opts.onState?.("open");
    });
    socket.addEventListener("message", (ev: MessageEvent) => {
      this.attempt = 0;
      this.refreshed = false;
      this.armSilence(socket);
      this.dispatch(ev.data);
    });
    socket.addEventListener("close", (ev: CloseEvent) => {
      this.onClose(socket, ev.code);
    });
  }

  private isStopped(): boolean {
    return this.stopped;
  }

  private dispatch(data: unknown): void {
    if (typeof data !== "string") return;
    let msg: unknown;
    try {
      msg = JSON.parse(data);
    } catch {
      return;
    }
    if (typeof msg !== "object" || msg === null) return;
    // A parsed JSON object: read its two known fields.
    const { type, number } = msg as { type?: unknown; number?: unknown };
    if (type === "order.changed" && typeof number === "string" && number) {
      this.opts.onChanged(number);
    }
    if (type === "sale.updated" && typeof number === "string" && number) {
      this.opts.onSaleChanged?.(number);
    }
  }

  private onClose(socket: WebSocket, code: number): void {
    if (this.socket !== socket) return; // a socket we already replaced or stopped
    this.socket = null;
    this.clearTimers();
    this.opts.onState?.("closed");
    if (this.stopped) return;
    if (code === UNAUTHORIZED && !this.refreshed && this.opts.refreshToken) {
      this.refreshed = true;
      void this.opts.refreshToken().finally(() => void this.connect());
      return;
    }
    this.retryLater();
  }

  private retryLater(): void {
    const base = Math.min(MAX_BACKOFF_MS, 500 * 2 ** this.attempt);
    const jitter = base * 0.2 * (this.opts.random ?? Math.random)();
    this.attempt += 1;
    this.retryTimer = setTimeout(() => void this.connect(), base + jitter);
  }

  private armSilence(socket: WebSocket): void {
    if (this.silenceTimer) clearTimeout(this.silenceTimer);
    this.silenceTimer = setTimeout(() => {
      socket.close();
    }, SILENCE_MS);
  }

  private clearTimers(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.silenceTimer) clearTimeout(this.silenceTimer);
    this.retryTimer = null;
    this.silenceTimer = null;
  }
}
