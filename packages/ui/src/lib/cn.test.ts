import { describe, expect, it } from "vitest";

import { cn } from "./cn";

describe("cn", () => {
  it("keeps a type-scale size beside a text colour", () => {
    expect(cn("text-small text-fg-muted")).toBe("text-small text-fg-muted");
  });

  it("lets a later size win over an earlier one", () => {
    expect(cn("text-small", "text-body")).toBe("text-body");
  });
});
