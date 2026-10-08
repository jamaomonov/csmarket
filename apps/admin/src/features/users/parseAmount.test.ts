import { describe, expect, it } from "vitest";

import { parseAmount, parseUsd } from "./parseAmount";

describe("parseAmount", () => {
  it("accepts a plain credit and an explicit plus", () => {
    expect(parseAmount("5000")).toBe(5000);
    expect(parseAmount("+5000")).toBe(5000);
  });

  it("flags a clawback with a minus", () => {
    expect(parseAmount("-10000")).toBe(-10000);
  });

  it("strips grouping spaces, including a pasted no-break space", () => {
    expect(parseAmount("50 000")).toBe(50000);
    expect(parseAmount("-1\u00a0250\u00a0000")).toBe(-1250000);
    expect(parseAmount(" 12\u202f920 ")).toBe(12920);
  });

  it("rejects what is not a whole number of soʻm", () => {
    // Scientific notation is never a deliberate customer credit.
    expect(parseAmount("1e9")).toBeNull();
    expect(parseAmount("--5")).toBeNull();
    expect(parseAmount("+-5")).toBeNull();
    expect(parseAmount("5.5")).toBeNull();
    expect(parseAmount("1250,50")).toBeNull();
    expect(parseAmount("5.5.5")).toBeNull();
    expect(parseAmount("abc")).toBeNull();
    expect(parseAmount("-")).toBeNull();
    expect(parseAmount("0x10")).toBeNull();
  });

  it("rejects empty input", () => {
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("   ")).toBeNull();
  });

  it("returns zero as zero (the form says why it is refused)", () => {
    expect(parseAmount("0")).toBe(0);
    expect(Object.is(parseAmount("-0"), 0)).toBe(true);
  });

  it("rejects a number beyond safe integer precision", () => {
    expect(parseAmount("99999999999999999999")).toBeNull();
  });
});

describe("parseUsd", () => {
  it.each([
    ["250", "250.000"],
    ["-30.5", "-30.500"],
    ["1000", "1000.000"],
    ["1000.5", "1000.500"],
    ["1 000.250", "1000.250"],
    ["+0.001", "0.001"],
    ["0", "0.000"],
    ["-0", "0.000"],
  ])("%s -> %s", (input, expected) => {
    expect(parseUsd(input)).toBe(expected);
  });

  it.each(["", "1.2345", "abc", "1e3", "--5", "1.", "1234567", "1,000", "1 000,5", "-30,5", "1,5"])(
    "refuses %j",
    (input) => {
      expect(parseUsd(input)).toBeNull();
    },
  );
});
