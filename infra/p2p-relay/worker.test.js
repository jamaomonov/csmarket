import { describe, expect, it, vi } from "vitest";

import { relay, same } from "./worker.js";

const ENV = {
  RELAY_SECRET: "relay-secret",
  YUPAY_URL: "https://yupay.example/p2p",
  YUPAY_SECRET: "yupay-secret",
  CSMARKET_URL: "https://csmarket.example/p2p",
  CSMARKET_SECRET: "csmarket-secret",
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

describe("relay", () => {
  it("refuses a wrong secret and forwards nothing", async () => {
    const f = fetcher({});
    const res = await relay(request("nope"), ENV, f);
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });

  it("answers 200 only when both projects answered 2xx, each with its own secret", async () => {
    const f = fetcher({});
    const res = await relay(request(), ENV, f);
    expect(res.status).toBe(200);
    const calls = f.mock.calls.map(([url, init]) => [
      url,
      init.headers["X-Telegram-Bot-Api-Secret-Token"],
      init.body,
    ]);
    expect(calls).toEqual([
      [ENV.YUPAY_URL, "yupay-secret", BODY],
      [ENV.CSMARKET_URL, "csmarket-secret", BODY],
    ]);
  });

  it("asks Telegram to retry when either project failed or threw", async () => {
    expect((await relay(request(), ENV, fetcher({ [ENV.CSMARKET_URL]: 500 }))).status).toBe(502);
    const throwing = vi.fn(async () => {
      throw new Error("down");
    });
    expect((await relay(request(), ENV, throwing)).status).toBe(502);
  });

  it("compares secrets by value", async () => {
    expect(await same("a", "a")).toBe(true);
    expect(await same("a", "b")).toBe(false);
    expect(await same("a", "")).toBe(false);
  });
});
