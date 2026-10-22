import { describe, expect, it } from "vitest";

import { compactSom } from "./labels";

describe("compactSom", () => {
  it("shortens to millions with one place and thousands with none", () => {
    expect(compactSom(3_742_121)).toMatch(/^3,7\sмлн$/);
    expect(compactSom("-492880")).toMatch(/^−493\sтыс$/);
    expect(compactSom(63_010)).toMatch(/^63\sтыс$/);
    expect(compactSom(950)).toBe("950");
    expect(compactSom(0)).toBe("0");
  });

  it("rounds up into the next unit and never shows «−0»", () => {
    expect(compactSom(999_600)).toMatch(/^1\sмлн$/);
    expect(compactSom(-999_600)).toMatch(/^−1\sмлн$/);
    expect(compactSom(999_950)).toMatch(/^1\sмлн$/);
    expect(compactSom("-0.4")).toBe("0");
    expect(compactSom("-0")).toBe("0");
  });
});
