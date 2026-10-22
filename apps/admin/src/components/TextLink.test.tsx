import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { TextLink } from "./TextLink";
import { UserCell } from "./UserCell";

describe("links look like links", () => {
  it("a number is an accent, monospace link", () => {
    render(
      <MemoryRouter>
        <TextLink to="/orders/O7K2M9QX" number>
          O7K2M9QX
        </TextLink>
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "O7K2M9QX" });
    expect(link).toHaveAttribute("href", "/orders/O7K2M9QX");
    expect(link).toHaveClass("text-accent", "font-mono");
  });

  it("a user's name is an accent link to the card", () => {
    render(
      <MemoryRouter>
        <UserCell id="u-1" name="Ivan" />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "Ivan" });
    expect(link).toHaveAttribute("href", "/users/u-1");
    expect(link).toHaveClass("text-accent");
  });
});
