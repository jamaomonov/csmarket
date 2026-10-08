import { describe, expect, it } from "vitest";

import { errorKey, shortTradeLink, verdictMessage } from "./trade-link";

describe("verdictMessage", () => {
  it("maps every state to copy", () => {
    expect(verdictMessage({ verdict: "ok", reason: null })).toEqual({ tone: "ok", key: "ok" });
    expect(verdictMessage({ verdict: "bad", reason: "hold" })).toEqual({
      tone: "bad",
      key: "hold",
    });
    expect(verdictMessage({ verdict: "bad", reason: "private" })).toEqual({
      tone: "bad",
      key: "private",
    });
    expect(verdictMessage({ verdict: "bad", reason: "trade_ban" })).toEqual({
      tone: "bad",
      key: "trade_ban",
    });
    expect(verdictMessage({ verdict: "bad", reason: null })).toEqual({
      tone: "bad",
      key: "invalid",
    });
    expect(verdictMessage({ verdict: null, reason: "unavailable" })).toEqual({
      tone: "muted",
      key: "unavailable",
    });
    expect(verdictMessage({ verdict: null, reason: null })).toBeNull();
  });
});

describe("verdictMessage, legacy warn", () => {
  it("shows a stored warn like a hold: the API no longer produces it, the DB may hold it", () => {
    expect(verdictMessage({ verdict: "warn", reason: "hold" })).toEqual({
      tone: "bad",
      key: "hold",
    });
  });
});

describe("errorKey", () => {
  it("knows the API codes and falls back", () => {
    expect(errorKey("trade_link_invalid")).toBe("trade_link_invalid");
    expect(errorKey("trade_link_not_yours")).toBe("trade_link_not_yours");
    expect(errorKey("something_else")).toBe("generic");
    expect(errorKey(undefined)).toBe("generic");
  });
});

describe("shortTradeLink", () => {
  it("keeps the host and partner and hides the token", () => {
    expect(
      shortTradeLink("https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE"),
    ).toEqual({ host: "steamcommunity.com", query: "?partner=1&token=••••••" });
  });

  it("gives up on anything else", () => {
    expect(shortTradeLink("not a link")).toBeNull();
    expect(shortTradeLink("https://example.com/x")).toBeNull();
  });
});
