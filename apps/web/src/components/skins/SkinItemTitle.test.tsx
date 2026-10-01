// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { SkinItemTitle } from "./SkinItemTitle";

const base = {
  weapon: "AK-47",
  stattrak: false,
  souvenir: false,
  phase: null,
  category: "Винтовки",
};

it("puts the weapon inside the H1, so twins on other weapons differ", () => {
  render(<SkinItemTitle {...base} name="Redline" />);
  const h1 = screen.getByRole("heading", { level: 1 });
  expect(h1).toHaveTextContent(/^AK-47 Redline$/);
});

it("names StatTrak™ and Souvenir in the H1 too", () => {
  const { unmount } = render(<SkinItemTitle {...base} stattrak name="Redline" />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^StatTrak™ AK-47 Redline$/);
  unmount();
  render(<SkinItemTitle {...base} weapon="AWP" souvenir name="Dragon Lore" phase={null} />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Souvenir AWP Dragon Lore$/);
});

it("keeps the phase in the H1", () => {
  render(<SkinItemTitle {...base} weapon="★ Karambit" name="Doppler" phase="Phase 2" />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    /^★ Karambit Doppler · Phase 2$/,
  );
});

it("leaves the category out of the H1 for an item with no weapon", () => {
  render(<SkinItemTitle {...base} weapon={null} name="Revolution Case" category="Кейсы" />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Revolution Case$/);
  expect(screen.getByText("Кейсы")).toBeInTheDocument();
});

it("keeps a StatTrak™ marker in the H1 even without a weapon", () => {
  render(
    <SkinItemTitle {...base} weapon={null} stattrak name="Sandstorm" category="Наборы музыки" />,
  );
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    /^StatTrak™ Наборы музыки Sandstorm$/,
  );
});
