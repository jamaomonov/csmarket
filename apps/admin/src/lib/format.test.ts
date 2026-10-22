import { describe, expect, it } from "vitest";

import {
  formatDateTime,
  formatDateTimeSeconds,
  formatRate,
  formatSignedSum,
  formatSum,
  listTime,
} from "./format";

describe("formatSum", () => {
  it("groups whole soʻm and names the unit", () => {
    expect(formatSum("30000")).toBe("30\u00a0000 сум");
    expect(formatSum(1250000)).toBe("1\u00a0250\u00a0000 сум");
  });
});

describe("formatSignedSum", () => {
  it("keeps the sign, with a typographic minus", () => {
    expect(formatSignedSum("+50000")).toBe("+50\u00a0000 сум");
    expect(formatSignedSum("-20000")).toBe("\u221220\u00a0000 сум");
    expect(formatSignedSum("700")).toBe("+700 сум");
  });
});

describe("formatDateTime", () => {
  it("renders DD.MM.YYYY HH:MM in local time", () => {
    const iso = new Date(2026, 9, 1, 9, 5).toISOString();
    expect(formatDateTime(iso)).toBe("01.10.2026 09:05");
  });
});

describe("listTime", () => {
  const NOW = new Date(2026, 9, 22, 12, 0, 0).getTime();
  const ago = (ms: number): string => new Date(NOW - ms).toISOString();
  const MIN = 60_000;

  it("is relative inside the last 24 hours", () => {
    expect(listTime(ago(20_000), NOW)).toBe("только что");
    expect(listTime(ago(-5 * MIN), NOW)).toBe("только что");
    expect(listTime(ago(3 * MIN), NOW)).toBe("3 мин назад");
    expect(listTime(ago(5 * 60 * MIN), NOW)).toBe("5 ч назад");
    expect(listTime(ago(24 * 60 * MIN - 1), NOW)).toBe("23 ч назад");
  });

  it("is absolute beyond: DD.MM HH:MM this year, DD.MM.YYYY an earlier one", () => {
    expect(listTime(new Date(2026, 9, 21, 9, 5).toISOString(), NOW)).toBe("21.10 09:05");
    expect(listTime(new Date(2025, 11, 31, 23, 0).toISOString(), NOW)).toBe("31.12.2025");
  });

  it("reads a rate as soʻm for a dollar, without trailing zeros", () => {
    expect(formatRate("12650.5000")).toBe("12\u00a0650,5\u00a0сум за $");
    expect(formatRate("12700.0000")).toBe("12\u00a0700\u00a0сум за $");
  });

  it("gives the exact time with seconds", () => {
    expect(formatDateTimeSeconds(new Date(2026, 9, 21, 9, 5, 7).toISOString())).toBe(
      "21.10.2026 09:05:07",
    );
  });
});
