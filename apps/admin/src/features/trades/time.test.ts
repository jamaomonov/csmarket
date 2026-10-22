import { describe, expect, it } from "vitest";

import { shortDate, timeLeft } from "./time";

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime();
const at = (ms: number): string => new Date(NOW + ms).toISOString();
const MIN = 60_000;

describe("trades time", () => {
  it("formats a hold's end date in local time", () => {
    const iso = new Date(2026, 9, 5, 9, 7, 3).toISOString();
    expect(shortDate(iso)).toBe("05.10");
  });

  it("says what is left of a hold", () => {
    expect(timeLeft(at((6 * 24 + 4) * 60 * MIN + 5 * MIN), NOW)).toBe("6д 4ч");
    expect(timeLeft(at(200 * MIN), NOW)).toBe("3ч 20м");
    expect(timeLeft(at(15 * MIN), NOW)).toBe("15м");
    expect(timeLeft(at(-MIN), NOW)).toBe("истекает");
  });
});
