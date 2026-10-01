import { describe, expect, it } from "vitest";

import { pick, upTo } from "./url-guards";

describe("pick", () => {
  it("keeps an allowed value and drops anything else", () => {
    const allowed = ["a", "b"] as const;
    expect(pick(allowed, "b")).toBe("b");
    expect(pick(allowed, "c")).toBeUndefined();
    expect(pick(allowed, "")).toBeUndefined();
  });
});

describe("upTo", () => {
  it("keeps text up to the limit and drops longer text", () => {
    expect(upTo("T7K", 32)).toBe("T7K");
    expect(upTo("x".repeat(32), 32)).toBe("x".repeat(32));
    expect(upTo("x".repeat(33), 32)).toBe("");
    expect(upTo("", 32)).toBe("");
  });
});
