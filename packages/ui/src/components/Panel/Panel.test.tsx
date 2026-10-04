import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Panel } from "./Panel";

describe("Panel", () => {
  it("renders the requested element with the panel surface", () => {
    render(<Panel as="aside">Фильтры</Panel>);
    const el = screen.getByText("Фильтры");
    expect(el.tagName).toBe("ASIDE");
    expect(el.className).toContain("bg-surface");
    expect(el.className).toContain("rounded-xl");
  });
});
