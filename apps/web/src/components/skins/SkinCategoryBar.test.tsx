// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import messages from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import { SkinCategoryBar } from "./SkinCategoryBar";

import type { SkinFacets, SkinQuery } from "@csmarket/utils/skins";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("./WeaponMenu", () => ({
  WeaponMenu: ({ label }: { label: string }) => <button type="button">{`menu:${label}`}</button>,
}));

const facets: SkinFacets = {
  categories: [
    { value: "rifles", count: 10 },
    { value: "cases", count: 4 },
    { value: "knives", count: 2 },
    { value: "music-kits", count: 3 },
  ],
  weapons: [
    { value: "AK-47", count: 5 },
    { value: "AWP", count: 4 },
    { value: "Galil AR", count: 9 },
  ],
  exteriors: [],
  rarities: [],
};

function bar(query: SkinQuery) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinCategoryBar query={query} facets={facets} />
    </NextIntlClientProvider>,
  );
}

it("chips carry silhouettes, knives first, and weapon categories get a model menu", () => {
  bar({ sort: "-price" });
  const links = screen.getAllByRole("link").map((a) => a.textContent);
  expect(links).toEqual(["Все", "Ножи", "Винтовки", "Кейсы", "Наборы музыки"]);
  expect(screen.getByRole("button", { name: "menu:Ножи" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "menu:Винтовки" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "menu:Кейсы" })).toBeNull();
  expect(document.querySelectorAll("[data-skin-icon]").length).toBeGreaterThanOrEqual(3);
  expect(screen.getByRole("link", { name: "Все" })).toHaveAttribute("aria-current", "page");
});

it("keeps a chosen weapon visible and clearable on the category chip", () => {
  bar({ sort: "-price", category: "rifles", weapon: "AK-47" });
  const chip = screen.getByRole("link", { name: /Винтовки · AK-47/ });
  expect(chip).toHaveAttribute("aria-current", "page");
  expect(chip).toHaveAttribute("href", "/?category=rifles");
});

it("unknown model stays clearable: the chip shows it and links back to the category", () => {
  bar({ sort: "-price", category: "rifles", weapon: "Foo" });
  const chip = screen.getByRole("link", { name: /Foo/ });
  expect(chip).toHaveAttribute("aria-current", "page");
  expect(chip.getAttribute("href")).not.toContain("weapon=");
});

it("the active chip's link has an offset focus ring (visible on green)", () => {
  bar({ sort: "-price", category: "rifles" });
  const chip = screen.getByRole("link", { name: "Винтовки" });
  expect(chip.className).toContain("focus-visible:ring-offset-2");
  expect(chip.className).toContain("focus-visible:ring-offset-bg");
});
