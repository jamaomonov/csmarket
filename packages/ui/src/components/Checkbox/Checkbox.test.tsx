import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CheckMark, Checkbox } from "./Checkbox";

describe("Checkbox", () => {
  it("toggles and keeps its label", () => {
    render(<Checkbox>Только StatTrak™</Checkbox>);
    const box = screen.getByRole("checkbox", { name: "Только StatTrak™" });
    fireEvent.click(box);
    expect(box).toBeChecked();
  });
  it("CheckMark shows the checked state for link-based filters", () => {
    render(<CheckMark checked />);
    expect(document.querySelector("[data-check='on']")).not.toBeNull();
  });
});
