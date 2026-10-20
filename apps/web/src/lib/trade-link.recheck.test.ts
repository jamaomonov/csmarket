import { describe, expect, it } from "vitest";

import { fixFor, needsCheck, RECHECK_AFTER_MS, STEAM_PRIVACY_PAGE } from "./trade-link";

const NOW = Date.parse("2026-10-20T10:00:00Z");
const ago = (ms: number): string => new Date(NOW - ms).toISOString();

describe("needsCheck", () => {
  it("asks for a link never checked or whose check was unavailable", () => {
    expect(needsCheck(null, null, NOW)).toBe(true);
  });

  it("asks again for a bad link: the buyer may have fixed Steam", () => {
    expect(needsCheck("bad", ago(1000), NOW)).toBe(true);
    expect(needsCheck("warn", ago(1000), NOW)).toBe(true);
  });

  it("trusts a fresh ok, and asks again once it is older than ten minutes", () => {
    expect(needsCheck("ok", ago(60_000), NOW)).toBe(false);
    expect(needsCheck("ok", ago(RECHECK_AFTER_MS + 1), NOW)).toBe(true);
    expect(needsCheck("ok", null, NOW)).toBe(true);
  });
});

describe("fixFor", () => {
  it("sends a hidden inventory to Steam's privacy settings", () => {
    expect(fixFor("private")).toEqual({ href: STEAM_PRIVACY_PAGE, label: "openPrivacy" });
  });

  it("sends a broken link to Steam's trade-URL page", () => {
    expect(fixFor("invalid")?.label).toBe("openTradeUrl");
  });

  it("offers nothing to click for a hold or a ban", () => {
    expect(fixFor("hold")).toBeNull();
    expect(fixFor("trade_ban")).toBeNull();
  });
});
