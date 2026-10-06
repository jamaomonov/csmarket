import { describe, expect, it } from "vitest";

import {
  BALANCE_BONUS_PERCENT,
  CARD_MIN_UZS,
  cardDigits,
  cardFits,
  formatCard,
  SELL_FEE_PERCENT,
  sellSummary,
} from "./sell";

describe("sell summary", () => {
  it("the balance: no fee, plus the bonus", () => {
    const s = sellSummary([100_000, 50_000], "balance");
    expect(s).toEqual({
      items: 150_000,
      fee: 0,
      bonus: Math.round((150_000 * BALANCE_BONUS_PERCENT) / 100),
      payout: 150_000 + Math.round((150_000 * BALANCE_BONUS_PERCENT) / 100),
    });
  });

  it("a card: the fee comes off, no bonus", () => {
    const s = sellSummary([200_000], "uzcard");
    const fee = Math.round((200_000 * SELL_FEE_PERCENT) / 100);
    expect(s).toEqual({ items: 200_000, fee, bonus: 0, payout: 200_000 - fee });
  });

  it("nothing chosen is zero everywhere", () => {
    expect(sellSummary([], "humo")).toEqual({ items: 0, fee: 0, bonus: 0, payout: 0 });
  });

  it("the card minimum is a real number", () => {
    expect(CARD_MIN_UZS).toBeGreaterThan(0);
  });
});

describe("card numbers", () => {
  it("keeps 16 digits and groups them by four", () => {
    expect(cardDigits("8600 12ab34-56781234567890")).toBe("8600123456781234");
    expect(formatCard("860012345678")).toBe("8600 1234 5678");
  });

  it("a card fits its method by the first digits", () => {
    expect(cardFits("uzcard", "8600123456781234")).toBe(true);
    expect(cardFits("humo", "9860123456781234")).toBe(true);
    expect(cardFits("uzum-visa", "4123123456781234")).toBe(true);
    expect(cardFits("humo", "8600123456781234")).toBe(false);
    expect(cardFits("uzcard", "86001234")).toBe(false); // not 16 digits yet
  });
});
