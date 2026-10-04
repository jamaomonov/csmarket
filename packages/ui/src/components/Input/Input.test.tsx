import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Input } from "./Input";

describe("Input", () => {
  it("is a raised field with the focus ring", () => {
    render(<Input aria-label="От" />);
    const el = screen.getByRole("textbox", { name: "От" });
    expect(el.className).toContain("bg-surface-2");
    expect(el.className).toContain("focus-visible:ring-accent");
  });
});
