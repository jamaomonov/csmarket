import { describe, expect, it } from "vitest";

import { formatDateTime, formatSignedSum, formatSum } from "./format";

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
