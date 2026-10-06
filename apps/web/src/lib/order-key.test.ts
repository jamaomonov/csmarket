import { describe, expect, it } from "vitest";

import { mintOrderKey, orderKeyFor } from "./order-key";

const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=fakeTok1";
const OTHER_LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=fakeTok2";

describe("orderKeyFor", () => {
  it("keeps one key per (offer, trade link), so a retry replays the same order", () => {
    let n = 0;
    const mint = () => `key-${String(++n)}`;
    const first = orderKeyFor(null, "wx:7", LINK, mint);
    expect(first).toEqual({ listingId: "wx:7", tradeLink: LINK, key: "key-1" });
    expect(orderKeyFor(first, "wx:7", LINK, mint)).toBe(first);
    expect(n).toBe(1);
  });

  it("mints a new key for another offer", () => {
    const first = orderKeyFor(null, "wx:7", LINK, () => "a");
    expect(orderKeyFor(first, "sl:8", LINK, () => "b").key).toBe("b");
  });

  it("mints a new key for another trade link: a replay would deliver to the old one", () => {
    const first = orderKeyFor(null, "wx:7", LINK, () => "a");
    expect(orderKeyFor(first, "wx:7", OTHER_LINK, () => "b")).toEqual({
      listingId: "wx:7",
      tradeLink: OTHER_LINK,
      key: "b",
    });
  });
});

describe("mintOrderKey", () => {
  it("fits the API's Idempotency-Key bounds and is never reused", () => {
    const a = mintOrderKey();
    expect(a.length).toBeGreaterThanOrEqual(16);
    expect(a.length).toBeLessThanOrEqual(160);
    expect(mintOrderKey()).not.toBe(a);
  });
});
