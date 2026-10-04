// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

import { Showcase, assertDevOnly } from "./page";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("dev UI showcase", () => {
  it("is not served in production", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(assertDevOnly).toThrow("NEXT_NOT_FOUND");
  });

  it("shows every token swatch and every component", () => {
    render(<Showcase />);
    for (const t of [
      "bg",
      "surface",
      "surface-2",
      "accent",
      "success",
      "danger",
      "rarity-covert",
    ]) {
      expect(screen.getByText(`--color-${t}`)).toBeInTheDocument();
    }
    for (const c of [
      "Button",
      "Chip",
      "Badge",
      "Input",
      "Select",
      "Checkbox",
      "Dropdown",
      "Accordion",
      "Panel",
    ]) {
      expect(screen.getByRole("heading", { name: c })).toBeInTheDocument();
    }
  });
});
