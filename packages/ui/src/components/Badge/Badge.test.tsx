import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "./Badge";

describe("Badge", () => {
  it("uses the subtle accent tone by default", () => {
    render(<Badge>−19%</Badge>);
    expect(screen.getByText("−19%").className).toContain("bg-accent-subtle");
  });
  it("supports a neutral tone", () => {
    render(<Badge tone="neutral">MW</Badge>);
    expect(screen.getByText("MW").className).toContain("bg-surface-2");
  });
});
