import { describe, expect, it } from "vitest";

import { capital, reasonText, reasonWord, statusText, statusWord } from "./dictionary";

describe("dictionary", () => {
  it("knows the statuses of every kind, lower-case", () => {
    expect(statusWord("payout", "to_pay")).toEqual({
      word: { label: "к выплате", tone: "info" },
      unknown: null,
    });
    expect(statusWord("trade", "hold").word.label).toBe("принят");
    expect(statusWord("order", "accepted").word.label).toBe("принят");
    expect(statusWord("trade", "delivered").word.label).toBe(
      statusWord("order", "delivered").word.label,
    );
  });

  it("an unknown status keeps its code", () => {
    expect(statusWord("payment", "lost")).toEqual({
      word: { label: "другой статус", tone: "muted" },
      unknown: "lost",
    });
    expect(statusText("payment", "lost")).toBe("другой статус (lost)");
  });

  it("an unknown reason reads «другая причина» and keeps its code", () => {
    expect(reasonWord("failure", "sold_out")).toEqual({ word: "скин продан", unknown: null });
    expect(reasonWord("return", "never_seen")).toEqual({
      word: "другая причина",
      unknown: "never_seen",
    });
    expect(reasonText("return", "never_seen")).toBe("другая причина (never_seen)");
  });

  it("never reads an inherited key as a word", () => {
    expect(reasonWord("failure", "toString").unknown).toBe("toString");
    expect(statusWord("order", "constructor").unknown).toBe("constructor");
  });

  it("capitalises a chip's word for a tab", () => {
    expect(capital("к выплате")).toBe("К выплате");
  });
});
