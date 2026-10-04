import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Select } from "./Select";

describe("Select", () => {
  it("renders a native select with its options", () => {
    render(
      <Select aria-label="Сортировка" defaultValue="b">
        <option value="a">A</option>
        <option value="b">B</option>
      </Select>,
    );
    expect(screen.getByRole("combobox", { name: "Сортировка" })).toHaveValue("b");
  });
});
