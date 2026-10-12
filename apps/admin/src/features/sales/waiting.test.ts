import { describe, expect, it } from "vitest";

import { waitingFor } from "./waiting";

const NOW = Date.parse("2026-10-12T12:00:00Z");

describe("waitingFor", () => {
  it("counts minutes, hours and days", () => {
    expect(waitingFor("2026-10-12T11:48:00Z", NOW)).toEqual({ text: "12 мин", level: "ok" });
    expect(waitingFor("2026-10-12T06:50:00Z", NOW)).toEqual({ text: "5 ч 10 мин", level: "ok" });
    expect(waitingFor("2026-10-12T05:00:00Z", NOW)).toEqual({ text: "7 ч 0 мин", level: "late" });
    expect(waitingFor("2026-10-11T09:00:00Z", NOW)).toEqual({ text: "1 д 3 ч", level: "overdue" });
    expect(waitingFor("2026-10-10T09:00:00Z", NOW)).toEqual({ text: "2 д 3 ч", level: "overdue" });
  });

  it("never goes negative", () => {
    expect(waitingFor("2026-10-12T13:00:00Z", NOW).text).toBe("0 мин");
  });
});
