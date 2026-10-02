import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderSocket, wsUrl, type SocketState } from "./realtime";

/** A WebSocket the test drives: it records sends and is opened / closed by hand. */
class FakeSocket {
  static all: FakeSocket[] = [];
  readonly sent: string[] = [];
  readonly url: string;
  closedByClient = false;
  private readonly listeners = new Map<string, ((ev: unknown) => void)[]>();

  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }

  addEventListener(type: string, fn: (ev: unknown) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closedByClient = true;
    this.emit("close", { code: 1000 });
  }

  emit(type: string, ev: unknown): void {
    for (const fn of this.listeners.get(type) ?? []) fn(ev);
  }

  open(): void {
    this.emit("open", {});
  }

  message(data: unknown): void {
    this.emit("message", { data: JSON.stringify(data) });
  }

  drop(code = 1006): void {
    this.emit("close", { code });
  }
}

const last = (): FakeSocket => {
  const s = FakeSocket.all.at(-1);
  if (!s) throw new Error("no socket");
  return s;
};

interface Harness {
  socket: OrderSocket;
  changed: string[];
  states: SocketState[];
  tokens: string[];
  refresh: ReturnType<typeof vi.fn>;
}

function harness(): Harness {
  const changed: string[] = [];
  const states: SocketState[] = [];
  const tokens = ["t1", "t2", "t3", "t4", "t5", "t6"];
  const refresh = vi.fn(() => Promise.resolve(true));
  const socket = new OrderSocket({
    url: "ws://api.test/api/v1/realtime/orders",
    getToken: () => Promise.resolve(tokens.shift() ?? null),
    refreshToken: refresh,
    onChanged: (n) => changed.push(n),
    onState: (s) => states.push(s),
    // The fake's shape is what OrderSocket uses of a WebSocket.
    WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
    random: () => 0,
  });
  return { socket, changed, states, tokens, refresh };
}

/** Let pending promise callbacks (the token read) run. */
const flush = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(0);
};

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
});

afterEach(() => {
  vi.useRealTimers();
});

describe("wsUrl", () => {
  it("maps the API origin to the socket path", () => {
    expect(wsUrl("http://localhost:8100")).toBe("ws://localhost:8100/api/v1/realtime/orders");
    expect(wsUrl("https://api.csmarket.uz/")).toBe("wss://api.csmarket.uz/api/v1/realtime/orders");
  });
});

describe("OrderSocket", () => {
  it("sends the auth frame first, with nothing in the URL", async () => {
    const h = harness();
    h.socket.start();
    await flush();
    expect(last().url).toBe("ws://api.test/api/v1/realtime/orders");
    last().open();
    expect(last().sent).toEqual([JSON.stringify({ type: "auth", token: "t1" })]);
    expect(h.states).toEqual(["connecting", "open"]);
  });

  it("reports a changed order and ignores pings and junk", async () => {
    const h = harness();
    h.socket.start();
    await flush();
    last().open();
    last().message({ type: "ping" });
    last().message({ type: "order.changed", number: "AB12CD34" });
    last().emit("message", { data: "not json" });
    last().message({ type: "order.changed" });
    expect(h.changed).toEqual(["AB12CD34"]);
  });

  it("reconnects after a drop with a fresh token, backing off", async () => {
    const h = harness();
    h.socket.start();
    await flush();
    last().open();
    last().drop();
    expect(h.states.at(-1)).toBe("closed");
    expect(FakeSocket.all).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(499);
    expect(FakeSocket.all).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.all).toHaveLength(2);
    last().open();
    expect(last().sent[0]).toBe(JSON.stringify({ type: "auth", token: "t2" }));
  });

  it("refreshes the token once on 4401, then backs off on a second 4401", async () => {
    const h = harness();
    h.socket.start();
    await flush();
    last().open();
    last().drop(4401);
    await flush();
    expect(h.refresh).toHaveBeenCalledTimes(1);
    expect(FakeSocket.all).toHaveLength(2); // straight back, no wait
    last().open();
    last().drop(4401);
    await flush();
    expect(h.refresh).toHaveBeenCalledTimes(1);
    expect(FakeSocket.all).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeSocket.all).toHaveLength(3);
  });

  it("closes a silent socket after 60 s and reconnects", async () => {
    const h = harness();
    h.socket.start();
    await flush();
    last().open();
    await vi.advanceTimersByTimeAsync(59_000);
    last().message({ type: "ping" });
    await vi.advanceTimersByTimeAsync(59_000);
    expect(last().closedByClient).toBe(false);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(FakeSocket.all[0]?.closedByClient).toBe(true);
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeSocket.all).toHaveLength(2);
    expect(h.states).toContain("closed");
  });

  it("stops for good: no reconnect after stop", async () => {
    const h = harness();
    h.socket.start();
    await flush();
    last().open();
    h.socket.stop();
    expect(last().closedByClient).toBe(true);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.all).toHaveLength(1);
  });

  it("waits and retries when there is no token", async () => {
    const h = harness();
    h.tokens.length = 0;
    h.socket.start();
    await flush();
    expect(FakeSocket.all).toHaveLength(0);
    h.tokens.push("late");
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeSocket.all).toHaveLength(1);
  });
});
