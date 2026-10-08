import { describe, expect, it } from "vitest";

import { ACCOUNT_NAV, isCurrent } from "./nav";

function entry(key: string) {
  const found = ACCOUNT_NAV.find((e) => e.key === key);
  if (!found) throw new Error(key);
  return found;
}
const trades = entry("trades");
const cards = entry("cards");

describe("isCurrent", () => {
  it("keeps «Обмены» current on an order's and a sale's page", () => {
    for (const path of ["/account/trades", "/orders/03TVB3PM", "/account/sales/SKMBK33X"]) {
      expect(isCurrent(trades, path)).toBe(true);
    }
    expect(isCurrent(cards, "/orders/03TVB3PM")).toBe(false);
  });
});
