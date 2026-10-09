import { describe, expect, it } from "vitest";

import { ago, clockTime, shortDate, shortDateTime, timeLeft } from "./time";

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime();
const at = (ms: number): string => new Date(NOW + ms).toISOString();
const MIN = 60_000;

describe("trades time", () => {
  it("formats the date and the clock in local time", () => {
    const iso = new Date(2026, 9, 5, 9, 7, 3).toISOString();
    expect(shortDateTime(iso)).toBe("05.10 09:07");
    expect(shortDate(iso)).toBe("05.10");
    expect(clockTime(iso)).toBe("09:07:03");
  });

  it("says how long ago", () => {
    expect(ago(at(-20_000), NOW)).toBe("только что");
    expect(ago(at(-3 * MIN), NOW)).toBe("3 мин назад");
    expect(ago(at(-5 * 60 * MIN), NOW)).toBe("5 ч назад");
    expect(ago(at(-49 * 60 * MIN), NOW)).toBe("2 д назад");
  });

  it("says what is left of a hold", () => {
    expect(timeLeft(at((6 * 24 + 4) * 60 * MIN + 5 * MIN), NOW)).toBe("6д 4ч");
    expect(timeLeft(at(200 * MIN), NOW)).toBe("3ч 20м");
    expect(timeLeft(at(15 * MIN), NOW)).toBe("15м");
    expect(timeLeft(at(-MIN), NOW)).toBe("истекает");
  });
});
