import { SessionApiError } from "@csmarket/api-client";
import { describe, expect, it } from "vitest";

import {
  cardDigits,
  cardFits,
  formatCard,
  luhnOk,
  nameParts,
  SellError,
  sellBody,
  sellError,
  sellSummary,
  type SellConfig,
} from "./sell";

const CONFIG: SellConfig = {
  enabled: true,
  balance_bonus_pct: "2",
  card_fee_pct: { uzcard: "5", humo: "5", uzum_visa: "1.5" },
  card_min_uzs: "30000",
  min_sum_uzs: "11300",
  max_cards: 3,
};

describe("sellSummary", () => {
  it("adds the balance bonus and rounds down to 100, like the API", () => {
    expect(sellSummary([149_600, 5_600], { to: "balance" }, CONFIG)).toEqual({
      items: 155_200,
      bonus: 3_100,
      fee: 0,
      payout: 158_300,
    });
  });

  it("takes the card type's fee, rounded down to 100", () => {
    const saved = { to: "saved", cardId: "c", type: "humo" } as const;
    expect(sellSummary([149_600, 5_600], saved, CONFIG)).toEqual({
      items: 155_200,
      bonus: 0,
      fee: 7_800,
      payout: 147_400,
    });
    const visa = { to: "new", type: "uzum_visa", digits: "" } as const;
    expect(sellSummary([155_200], visa, CONFIG).payout).toBe(152_800); // 152 872 → 152 800
  });
});

describe("cards", () => {
  it("keeps 16 digits and groups them by four", () => {
    expect(cardDigits("9860 1234-5678 90151234")).toBe("9860123456789015");
    expect(formatCard("98601234")).toBe("9860 1234");
  });

  it("checks the type's prefix and Luhn", () => {
    expect(luhnOk("9860123456789015")).toBe(true);
    expect(luhnOk("9860123456789016")).toBe(false);
    expect(cardFits("humo", "9860123456789015")).toBe(true);
    expect(cardFits("uzcard", "9860123456789015")).toBe(false);
    expect(cardFits("uzum_visa", "4000000000000002")).toBe(true);
    expect(cardFits("humo", "986012345678901")).toBe(false);
  });
});

describe("nameParts", () => {
  it("splits a market name into weapon and skin", () => {
    expect(nameParts("StatTrak™ AK-47 | Redline (Field-Tested)")).toEqual({
      weapon: "AK-47",
      skin: "Redline",
      stattrak: true,
    });
    expect(nameParts("★ Karambit | Fade (Factory New)")).toEqual({
      weapon: "Karambit",
      skin: "Fade",
      stattrak: false,
    });
    expect(nameParts("Sticker Capsule")).toEqual({
      weapon: null,
      skin: "Sticker Capsule",
      stattrak: false,
    });
  });
});

describe("sellBody", () => {
  it("names the card the API's way", () => {
    expect(sellBody(["1"], { to: "balance" }, 10)).toEqual({
      asset_ids: ["1"],
      payout: { to: "balance" },
      expected_payout_uzs: 10,
    });
    expect(sellBody(["1"], { to: "saved", cardId: "c1", type: "humo" }, 10).payout).toEqual({
      to: "card",
      card_id: "c1",
    });
    expect(
      sellBody(["1"], { to: "new", type: "humo", digits: "9860123456789015" }, 10).payout,
    ).toEqual({ to: "card", new_card: { type: "humo", number: "9860123456789015" } });
  });
});

describe("sellError", () => {
  it("reads the code and the Steam reason of an API refusal", () => {
    const err = sellError(
      new SessionApiError(409, "Conflict", { code: "steam_refused", reason: "hold" }),
    );
    expect(err).toBeInstanceOf(SellError);
    expect(err?.code).toBe("steam_refused");
    expect(err?.reason).toBe("hold");
    expect(
      sellError(new SessionApiError(503, "Unavailable", { code: "rate_unavailable" }))?.code,
    ).toBe("rate_unavailable");
  });

  it("passes an already converted error through", () => {
    const err = new SellError("prices_changed", null);
    expect(sellError(err)).toBe(err);
  });

  it("leaves other errors alone", () => {
    expect(sellError(new Error("x"))).toBeNull();
    expect(sellError(new SessionApiError(500, "x", { code: "weird" }))).toBeNull();
  });
});
