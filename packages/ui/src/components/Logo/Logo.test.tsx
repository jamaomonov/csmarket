import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Logo, LogoMark } from "./Logo";

describe("Logo", () => {
  it("the mark is two arrows and a gem in the current colour, hidden from readers", () => {
    const { container } = render(<LogoMark className="size-8" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg?.getAttribute("class")).toContain("size-8");
    const paths = container.querySelectorAll("path");
    expect(paths).toHaveLength(3);
    for (const p of paths) expect(p).toHaveAttribute("fill", "currentColor");
  });

  it("the lockup is the green mark beside «csmarket» with «market» in green", () => {
    const { container } = render(<Logo />);
    expect(container.textContent).toBe("csmarket");
    expect(screen.getByText("market").className).toContain("text-accent");
    expect(container.querySelector("svg")?.getAttribute("class")).toContain("text-accent");
    // The wordmark leans with the arrows (14°) and sits tight to the mark.
    const word = screen.getByText("market").parentElement;
    expect(word?.className.split(" ")).toEqual(
      expect.arrayContaining(["-skew-x-[14deg]", "tracking-[-0.045em]"]),
    );
  });
});
