import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Chip, chipVariants } from "./Chip";

describe("Chip", () => {
  it("reports its pressed state and shows the icon before the label", () => {
    render(
      <Chip active icon={<span data-testid="ico" />}>
        Ножи
      </Chip>,
    );
    const chip = screen.getByRole("button", { name: "Ножи" });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(chip.firstElementChild).toBe(screen.getByTestId("ico"));
    expect(chip.className.split(" ")).toContain("bg-accent");
  });

  it("is a plain surface chip when inactive", () => {
    render(<Chip>Кейсы</Chip>);
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
    expect(chipVariants({ active: false }).split(" ")).toContain("bg-surface");
  });
});
