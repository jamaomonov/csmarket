import { describe, expect, it } from "vitest";

import { kassaCharge, kassaFee } from "./kassa-fee";

describe("kassaFee", () => {
  it("is the percent rounded up to whole soʻm, as the API counts it", () => {
    expect(kassaFee(100000, "0")).toBe(0);
    expect(kassaFee(100000, "1")).toBe(1000);
    expect(kassaFee(100000, "1.5")).toBe(1500);
    expect(kassaFee(33333, "1.5")).toBe(500);
    expect(kassaFee(1, "0.01")).toBe(1);
    expect(kassaFee(123456789, "2.35")).toBe(2901235);
  });
});

describe("kassaCharge", () => {
  const kassas = [
    { slug: "click", fee_pct: "1" },
    { slug: "payme", fee_pct: "0" },
  ];

  it("adds the chosen kassa's fee", () => {
    expect(kassaCharge(100000, kassas, "click")).toEqual({
      slug: "click",
      fee: 1000,
      total: 101000,
    });
  });

  it("is null for the balance, a kassa without a fee or no choice", () => {
    expect(kassaCharge(100000, kassas, "wallet")).toBeNull();
    expect(kassaCharge(100000, kassas, "payme")).toBeNull();
    expect(kassaCharge(100000, kassas, null)).toBeNull();
    expect(kassaCharge(100000, undefined, "click")).toBeNull();
  });
});
