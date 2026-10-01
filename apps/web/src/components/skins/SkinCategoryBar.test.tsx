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

const facets: SkinFacets = {
  categories: [
    { value: "rifles", count: 10 },
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

it("keeps a chosen weapon visible and clearable", () => {
  bar({ sort: "-price", category: "rifles", weapon: "AK-47" });
  const chip = screen.getByRole("link", { name: "AK-47" });
  expect(chip).toHaveAttribute("aria-current", "page");
  expect(chip).toHaveAttribute("href", "/?category=rifles");
});

it("lists every weapon of the category from the facets, in their order", () => {
  bar({ sort: "-price", category: "rifles" });
  const names = ["AK-47", "AWP", "Galil AR"].map((n) => screen.getByRole("link", { name: n }));
  expect(names).toHaveLength(3);
});

it("draws each category tile with its silhouette icon", () => {
  bar({ sort: "-price", category: "rifles" });
  const tile = screen.getByRole("link", { name: "Винтовки" });
  expect(tile).toHaveAttribute("aria-current", "page");
  const icon = tile.querySelector("[data-skin-icon]");
  expect(icon?.getAttribute("style")).toContain("/skins/categories/rifles.png");
  // Music kits have no item image — a glyph stands in.
  expect(screen.getByRole("link", { name: "Наборы музыки" }).querySelector("svg")).not.toBeNull();
});
