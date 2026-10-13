// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://csmarket.uz/market"}
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { gaEnabled, purchaseEvent, track, trackPurchase } from "./analytics";

const NOW = Date.parse("2026-10-13T12:00:00Z");

const order = {
  number: "K7M2Q9XA",
  status: "delivered",
  slug: "ak-47-redline-field-tested",
  name: "AK-47 | Redline (Field-Tested)",
  price_uzs: "245000",
  paid_at: "2026-10-13T11:50:00Z",
};

describe("gaEnabled", () => {
  it("counts only csmarket.uz", () => {
    expect(gaEnabled("csmarket.uz")).toBe(true);
    expect(gaEnabled("www.csmarket.uz")).toBe(false);
    expect(gaEnabled("localhost")).toBe(false);
  });
});

describe("purchaseEvent", () => {
  it("describes a freshly paid order with its number, sum and skin only", () => {
    expect(purchaseEvent(order, NOW, [])).toEqual({
      name: "purchase",
      params: {
        transaction_id: "K7M2Q9XA",
        currency: "UZS",
        value: 245000,
        items: [
          {
            item_id: "ak-47-redline-field-tested",
            item_name: "AK-47 | Redline (Field-Tested)",
            price: 245000,
          },
        ],
      },
    });
  });

  it("skips unpaid, old and already sent orders", () => {
    expect(purchaseEvent({ ...order, status: "pending", paid_at: null }, NOW, [])).toBeNull();
    expect(purchaseEvent({ ...order, status: "cancelled" }, NOW, [])).toBeNull();
    expect(purchaseEvent({ ...order, paid_at: "2026-10-13T10:00:00Z" }, NOW, [])).toBeNull();
    expect(purchaseEvent(order, NOW, ["K7M2Q9XA"])).toBeNull();
  });
});

describe("track", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    delete window.gtag;
    window.localStorage.clear();
  });

  it("sends through gtag when the tag is on the page", () => {
    const gtag = vi.fn();
    window.gtag = gtag;
    track({ name: "login", params: { method: "steam" } });
    expect(gtag).toHaveBeenCalledWith("event", "login", { method: "steam" });
  });

  it("waits for a tag that is still loading", () => {
    const gtag = vi.fn();
    track({ name: "login", params: { method: "steam" } });
    window.gtag = gtag;
    vi.advanceTimersByTime(500);
    expect(gtag).toHaveBeenCalledTimes(1);
  });

  it("counts a purchase once per browser", () => {
    vi.setSystemTime(NOW);
    const gtag = vi.fn();
    window.gtag = gtag;
    trackPurchase(order);
    trackPurchase(order);
    expect(gtag).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(gtag.mock.calls)).not.toMatch(/steam_?id|email|trade/i);
  });
});
