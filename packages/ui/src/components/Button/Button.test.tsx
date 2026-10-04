import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("renders its children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: "Click me" })).toBeInTheDocument();
  });

  it("applies the primary variant by default", () => {
    render(<Button>Primary</Button>);
    const btn = screen.getByRole("button");
    expect(btn.className).toContain("bg-accent");
  });
  it("has one focus style and a raised secondary", () => {
    render(<Button variant="secondary">S</Button>);
    const btn = screen.getByRole("button");
    expect(btn.className).toContain("focus-visible:ring-accent");
    expect(btn.className.split(" ")).toContain("bg-surface-2");
  });
});
