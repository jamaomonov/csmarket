import { describe, expect, it } from "vitest";

import { kindLabel } from "./labels";

describe("kindLabel", () => {
  it("names every ledger kind in Russian", () => {
    expect(kindLabel("topup")).toBe("Пополнение");
    expect(kindLabel("purchase")).toBe("Покупка");
    expect(kindLabel("refund")).toBe("Возврат на баланс");
  });

  it("falls back to the raw kind", () => {
    expect(kindLabel("sell_payout")).toBe("sell_payout");
  });
});
