import en from "@csmarket/i18n/locales/en/web.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import uz from "@csmarket/i18n/locales/uz/web.json";
import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { categoryMd, homeMd, itemMd, marketMd } from "./agent-md-pages";

import type { SkinDetail } from "@csmarket/utils/skins";

const MESSAGES = { ru, uz, en } as const;
vi.mock("next-intl/server", () => ({
  getTranslations: ({ locale, namespace }: { locale: "ru" | "uz" | "en"; namespace: string }) =>
    Promise.resolve(
      createTranslator({
        locale,
        messages: { web: MESSAGES[locale] },
        namespace: namespace as "web", // the real catalogue; namespaces passed as plain strings
      }),
    ),
}));

const ITEM: SkinDetail = {
  slug: "ak-47-redline-field-tested",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  skin: "Redline",
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  rarity: "Classified",
  rarity_color: "#d32ce6",
  image_url: null,
  price_usd: "27.1",
  price_uzs: "342600",
  steam_price_usd: null,
  discount_percent: null,
  count: 687,
  min_float: "0.10",
  max_float: "0.70",
  cheapest: [],
  family: [
    {
      slug: "ak-47-redline-field-tested",
      exterior: "FT",
      stattrak: false,
      souvenir: false,
      price_usd: "27.1",
      price_uzs: "342600",
      count: 687,
    },
    {
      slug: "stattrak-ak-47-redline-well-worn",
      exterior: "WW",
      stattrak: true,
      souvenir: false,
      price_usd: "50",
      price_uzs: "636500",
      count: 3,
    },
  ],
  collection: "The Phoenix Collection",
  crates: [{ name: "Operation Phoenix Weapon Case", slug: null }],
  description: null,
  buy_enabled: true,
};

vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getSkinDetail: (slug: string) => Promise.resolve(slug === ITEM.slug ? ITEM : null),
  getSkinFacets: () =>
    Promise.resolve({
      categories: [{ value: "knives", count: 3069 }],
      weapons: [],
      exteriors: [],
      rarities: [],
    }),
  getSkinsPage: () => Promise.resolve({ items: [ITEM], next_cursor: null }),
}));

describe("Markdown twins", () => {
  it("an item: name, price, facts, other wears, FAQ and its URL", async () => {
    const md = await itemMd("ru", ITEM.slug);
    expect(md).toContain("# AK-47 | Redline (Field-Tested)");
    expect(md).toMatch(/от 342\s600 сум · В наличии: 687 шт\./);
    expect(md).toContain("- Float: 0.10–0.70");
    expect(md).toContain(
      "[StatTrak™ Поношенное](https://csmarket.uz/item/stattrak-ak-47-redline-well-worn)",
    );
    expect(md).toContain("## Частые вопросы");
    expect(md?.trimEnd().endsWith("https://csmarket.uz/item/ak-47-redline-field-tested")).toBe(
      true,
    );
  });

  it("an unknown item or category is null (a 404)", async () => {
    expect(await itemMd("ru", "nope")).toBeNull();
    expect(await categoryMd("ru", "nope")).toBeNull();
  });

  it("the market lists the categories and the items, in the asked language", async () => {
    const md = await marketMd("en");
    expect(md).toContain("[Knives](https://csmarket.uz/en/category/knives) (3069)");
    expect(md).toContain("(https://csmarket.uz/en/item/ak-47-redline-field-tested)");
  });

  it("the home page says what the shop is and answers its FAQ", async () => {
    const md = await homeMd("uz");
    expect(md.startsWith("# ")).toBe(true);
    expect(md).toContain("https://csmarket.uz/uz/market");
    expect(md).toContain("### ");
  });
});
