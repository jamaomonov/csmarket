import { describe, expect, it } from "vitest";

import { formatUzs, uzsWord } from "./money";

describe("money", () => {
  it("names the currency per locale", () => {
    expect(uzsWord("ru")).toBe("сум");
    expect(uzsWord("uz")).toBe("soʻm");
    expect(uzsWord("en")).toBe("UZS");
  });
  it("groups whole soʻm", () => {
    expect(formatUzs("ru", "1234500")).toMatch(/^1\s234\s500 сум$/u);
    expect(formatUzs("en", 1234500)).toBe("1,234,500 UZS");
  });
});
