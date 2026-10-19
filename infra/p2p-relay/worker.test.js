import { describe, expect, it, vi } from "vitest";

import { relay, same, consumeCsmarket } from "./worker.js";

const ENV = {
  RELAY_SECRET: "relay-secret",
  YUPAY_URL: "https://yupay.example/p2p",
  YUPAY_SECRET: "yupay-secret",
  CSMARKET_URL: "https://csmarket.example/p2p",
  CSMARKET_SECRET: "csmarket-secret",
  RELAY_BACKOFF_MS: "0",
};
const BODY = JSON.stringify({ update_id: 1, business_message: { message_id: 7 } });

function request(secret = "relay-secret", body = BODY) {
  return new Request("https://relay.example/", {
    method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": secret },
    body,
  });
}

function fetcher(statuses) {
  return vi.fn(async (url) => new Response("", { status: statuses[url] ?? 200 }));
}

function ctx() {
  const waits = [];
  return { waitUntil: (p) => waits.push(p), waits };
}

describe("relay", () => {
  it("refuses a wrong secret and forwards nothing", async () => {
    const f = fetcher({});
    const res = await relay(request("nope"), ENV, ctx(), f);
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });

  it("answers Telegram on YuPay's 2xx and queues csmarket's delivery", async () => {
    const f = fetcher({});
    const queue = { send: vi.fn(async () => undefined) };
    const res = await relay(request(), { ...ENV, CSMARKET_QUEUE: queue }, ctx(), f);
    expect(res.status).toBe(200);
    expect(f).toHaveBeenCalledOnce();
    expect(f.mock.calls[0][0]).toBe(ENV.YUPAY_URL);
    expect(f.mock.calls[0][1].headers["X-Telegram-Bot-Api-Secret-Token"]).toBe("yupay-secret");
    expect(queue.send).toHaveBeenCalledWith({ body: BODY });
  });

  it("asks Telegram to retry only when YuPay failed — csmarket down never blocks YuPay", async () => {
    const down = fetcher({ [ENV.YUPAY_URL]: 500 });
    expect((await relay(request(), ENV, ctx(), down)).status).toBe(502);
    const csmarketDown = fetcher({ [ENV.CSMARKET_URL]: 500 });
    const c = ctx();
    expect((await relay(request(), ENV, c, csmarketDown)).status).toBe(200);
    await Promise.all(c.waits); // without a queue: background retries, logged
    const csmarketCalls = csmarketDown.mock.calls.filter(([url]) => url === ENV.CSMARKET_URL);
    expect(csmarketCalls).toHaveLength(4);
  });

  it("falls back to background retries when the queue refuses", async () => {
    const f = fetcher({});
    const queue = {
      send: vi.fn(async () => {
        throw new Error("queue down");
      }),
    };
    const c = ctx();
    const res = await relay(request(), { ...ENV, CSMARKET_QUEUE: queue }, c, f);
    expect(res.status).toBe(200);
    await Promise.all(c.waits);
    expect(f.mock.calls.map(([url]) => url)).toEqual([ENV.YUPAY_URL, ENV.CSMARKET_URL]);
  });

  it("the queue consumer retries a csmarket failure and acks a success", async () => {
    const ok = { body: { body: BODY }, ack: vi.fn(), retry: vi.fn() };
    const bad = { body: { body: BODY }, ack: vi.fn(), retry: vi.fn() };
    await consumeCsmarket({ messages: [ok] }, ENV, fetcher({}));
    await consumeCsmarket({ messages: [bad] }, ENV, fetcher({ [ENV.CSMARKET_URL]: 503 }));
    expect(ok.ack).toHaveBeenCalledOnce();
    expect(bad.retry).toHaveBeenCalledOnce();
    expect(bad.ack).not.toHaveBeenCalled();
  });

  it("compares secrets by value", async () => {
    expect(await same("a", "a")).toBe(true);
    expect(await same("a", "b")).toBe(false);
    expect(await same("a", "")).toBe(false);
  });
});
