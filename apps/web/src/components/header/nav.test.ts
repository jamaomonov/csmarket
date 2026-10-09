import { describe, expect, it } from "vitest";

import { ACCOUNT_NAV, isCurrent, MAIN_NAV } from "./nav";

function entry(key: string) {
  const found = ACCOUNT_NAV.find((e) => e.key === key);
  if (!found) throw new Error(key);
  return found;
}
const trades = entry("trades");
const cards = entry("transactions");

describe("isCurrent", () => {
  it("keeps «Обмены» current on an order's and a sale's page", () => {
    for (const path of ["/account/trades", "/orders/03TVB3PM", "/account/sales/SKMBK33X"]) {
      expect(isCurrent(trades, path)).toBe(true);
    }
    expect(isCurrent(cards, "/orders/03TVB3PM")).toBe(false);
  });
});

describe("isCurrent for the market", () => {
  const market = MAIN_NAV.find((e) => e.key === "market");
  it("is the catalogue and every skin page, never the landing", () => {
    expect(market).toBeDefined();
    if (!market) return;
    for (const path of ["/market", "/item/ak-47-redline", "/category/knives", "/weapon/ak-47"]) {
      expect(isCurrent(market, path)).toBe(true);
    }
    expect(isCurrent(market, "/")).toBe(false);
  });
});
