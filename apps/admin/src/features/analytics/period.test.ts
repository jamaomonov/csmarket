import { describe, expect, it } from "vitest";

import { fromParams, monthOf, shiftMonth, tashkentToday, toParams, windowOf } from "./period";

describe("period", () => {
  it("takes the last N days ending today", () => {
    expect(windowOf({ kind: "days", days: 30 }, "2026-10-19")).toEqual({
      since: "2026-09-20",
      until: "2026-10-19",
    });
  });

  it("spans a whole month, leap February included", () => {
    expect(windowOf({ kind: "month", month: "2028-02" }, "2026-10-19")).toEqual({
      since: "2028-02-01",
      until: "2028-02-29",
    });
  });

  it("keeps a range as given", () => {
    expect(windowOf({ kind: "range", since: "2026-10-09", until: "2026-10-12" }, "x")).toEqual({
      since: "2026-10-09",
      until: "2026-10-12",
    });
  });

  it("round-trips the URL and falls back to 30 days on junk", () => {
    const p = { kind: "range", since: "2026-10-09", until: "2026-10-09" } as const;
    expect(fromParams((k) => toParams(p)[k] ?? "")).toEqual(p);
    expect(fromParams((k) => ({ from: "nope", to: "2026-10-09" })[k] ?? "")).toEqual({
      kind: "days",
      days: 30,
    });
    expect(fromParams((k) => ({ m: "2026-10" })[k] ?? "")).toEqual({
      kind: "month",
      month: "2026-10",
    });
  });

  it("steps months and reads Tashkent's date", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(monthOf("2026-10-19")).toBe("2026-10");
    // 2026-10-18 20:30 UTC is already the 19th in Tashkent (UTC+5).
    expect(tashkentToday(new Date("2026-10-18T20:30:00Z"))).toBe("2026-10-19");
  });
});
