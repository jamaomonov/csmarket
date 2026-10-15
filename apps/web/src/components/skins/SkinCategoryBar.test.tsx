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
  // The real one is a Dropdown whose trigger is the whole chip (WeaponMenu.test.tsx).
  WeaponMenu: ({ trigger }: { trigger: React.ReactNode }) => (
    <button type="button">{trigger}</button>
  ),
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

/** The chip (the span around a weapon category's menu) whose button reads `name`. */
const chipOf = (name: RegExp | string) => screen.getByRole("button", { name }).parentElement;

it("chips carry silhouettes, knives first, each weapon category is one menu button, no «Все»", () => {
  bar({ sort: "-price" });
  const buttons = screen
    .getAllByRole("button")
    .map((b) => b.textContent)
    .filter((t) => !t.startsWith("other:"));
  expect(buttons).toEqual(["Ножи", "Винтовки", "П-пулемёты", "Тяжёлое"]);
  expect(screen.queryAllByRole("link")).toHaveLength(0);
  expect(document.querySelectorAll("[data-skin-icon]").length).toBeGreaterThanOrEqual(3);
  expect(screen.queryByRole("button", { name: "Все" })).toBeNull();
});

it("the chosen category's chip is marked active", () => {
  bar({ sort: "-price", category: "rifles" });
  expect(chipOf("Винтовки")).toHaveAttribute("data-active");
  expect(chipOf("Ножи")).not.toHaveAttribute("data-active");
});

it("a chosen weapon shows on its chip", () => {
  bar({ sort: "-price", category: "rifles", weapon: "AK-47" });
  expect(chipOf(/Винтовки · AK-47/)).toHaveAttribute("data-active");
});

it("several models across categories light each chip with its own", () => {
  bar({ sort: "-price", weapon: "AK-47,AWP,MP9" });
  expect(chipOf(/Винтовки · 2/)).toHaveAttribute("data-active");
  expect(chipOf(/П-пулемёты · MP9/)).toHaveAttribute("data-active");
});

it("an unknown model still shows on the chosen category's chip", () => {
  bar({ sort: "-price", category: "rifles", weapon: "Foo" });
  expect(chipOf(/Foo/)).toHaveAttribute("data-active");
});

it("agents, cases, keys and the rest collapse into one «Другое» menu after the weapons", () => {
  bar({ sort: "-price" });
  // In ORDER, only the present ones: agents, cases, music-kits.
  expect(
    screen.getByRole("button", { name: "other:agents,cases,music-kits:" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Кейсы" })).toBeNull();
  bar({ sort: "-price", category: "cases" });
  const chosen = screen.getByRole("button", { name: "other:agents,cases,music-kits:cases" });
  // The row scrolls it into view on a phone.
  expect(chosen.closest("[data-active]")).not.toBeNull();
});

it("one row: chips never wrap, inactive ones are flat inside the panel", () => {
  bar({ sort: "-price", category: "rifles" });
  const knives = chipOf("Ножи");
  const row = knives?.parentElement;
  expect(row?.className.split(" ")).not.toContain("lg:flex-wrap");
  expect(row?.className.split(" ")).toContain("overflow-x-auto");
  expect(knives?.className.split(" ")).toContain("bg-transparent");
  expect(knives?.className.split(" ")).not.toContain("bg-surface");
});

it("on a wide screen the chips share the panel's width, none left over at the end", () => {
  bar({ sort: "-price" });
  expect(chipOf("Ножи")?.className.split(" ")).toContain("lg:flex-1");
  const other = screen.getByRole("button", { name: /other:/ }).parentElement;
  expect(other?.className.split(" ")).toContain("lg:flex-1");
});
