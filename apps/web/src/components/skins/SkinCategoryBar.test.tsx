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
vi.mock("./OtherCategoriesMenu", () => ({
  OtherCategoriesMenu: ({ categories, active }: { categories: string[]; active?: string }) => (
    <button type="button">{`other:${categories.join(",")}:${active ?? ""}`}</button>
  ),
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
    { value: "smgs", count: 6 },
    { value: "agents", count: 1 },
    { value: "heavy", count: 2 },
  ],
  weapons: [
    { value: "AK-47", count: 5, category: "rifles" },
    { value: "AWP", count: 4, category: "rifles" },
    { value: "Galil AR", count: 9, category: "rifles" },
    { value: "MP9", count: 2, category: "smgs" },
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

it("chips carry silhouettes, knives first, weapon categories get a model menu, no «Все»", () => {
  bar({ sort: "-price" });
  const links = screen.getAllByRole("link").map((a) => a.textContent);
  expect(links).toEqual(["Ножи", "Винтовки", "П-пулемёты", "Тяжёлое"]);
  expect(screen.getByRole("button", { name: "menu:Ножи" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "menu:Винтовки" })).toBeInTheDocument();
  expect(document.querySelectorAll("[data-skin-icon]").length).toBeGreaterThanOrEqual(3);
  expect(screen.queryByRole("link", { name: "Все" })).toBeNull();
});

it("the chosen category's chip clears it", () => {
  bar({ sort: "-price", category: "rifles" });
  const chip = screen.getByRole("link", { name: "Винтовки" });
  expect(chip).toHaveAttribute("aria-current", "page");
  expect(chip).toHaveAttribute("href", "/market");
});

it("a chosen weapon shows on its chip; the chip clears the models", () => {
  bar({ sort: "-price", category: "rifles", weapon: "AK-47" });
  const chip = screen.getByRole("link", { name: /Винтовки · AK-47/ });
  expect(chip).toHaveAttribute("aria-current", "page");
  expect(chip).toHaveAttribute("href", "/market");
});

it("several models across categories light each chip with its own", () => {
  bar({ sort: "-price", weapon: "AK-47,AWP,MP9" });
  expect(screen.getByRole("link", { name: /Винтовки · 2/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  // Clearing the rifles keeps the other category's model.
  expect(screen.getByRole("link", { name: /Винтовки · 2/ })).toHaveAttribute(
    "href",
    "/market?weapon=MP9",
  );
  expect(screen.getByRole("link", { name: /П-пулемёты · MP9/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

it("an unknown model stays clearable from the category chip", () => {
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

it("agents, cases, keys and the rest collapse into one «Другое» menu after the weapons", () => {
  bar({ sort: "-price" });
  // In ORDER, only the present ones: agents, cases, music-kits.
  expect(
    screen.getByRole("button", { name: "other:agents,cases,music-kits:" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Кейсы" })).toBeNull();
  bar({ sort: "-price", category: "cases" });
  const chosen = screen.getByRole("button", { name: "other:agents,cases,music-kits:cases" });
  // The row scrolls it into view on a phone.
  expect(chosen.closest("[data-active]")).not.toBeNull();
});

it("one row: chips never wrap, inactive ones are flat inside the panel", () => {
  bar({ sort: "-price", category: "rifles" });
  const knives = screen.getByRole("link", { name: "Ножи" }).parentElement;
  const row = knives?.parentElement;
  expect(row?.className.split(" ")).not.toContain("lg:flex-wrap");
  expect(row?.className.split(" ")).toContain("overflow-x-auto");
  expect(knives?.className.split(" ")).toContain("bg-transparent");
  expect(knives?.className.split(" ")).not.toContain("bg-surface");
});

it("on a wide screen the chips share the panel's width, none left over at the end", () => {
  bar({ sort: "-price" });
  const knives = screen.getByRole("link", { name: "Ножи" }).parentElement;
  expect(knives?.className.split(" ")).toContain("lg:flex-1");
  const other = screen.getByRole("button", { name: /other:/ }).parentElement;
  expect(other?.className.split(" ")).toContain("lg:flex-1");
});
