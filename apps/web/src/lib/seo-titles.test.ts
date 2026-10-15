import en from "@csmarket/i18n/locales/en/web.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

/**
 * The search titles say what people type (Keyword Planner, Uzbekistan, 2026-10-15): «cs2 skin»
 * is the one big query, and Russian searches say «кс го» more than «кс2».
 */
describe("search titles", () => {
  const tRu = createTranslator({ locale: "ru", messages: { web: ru }, namespace: "web" });
  const tEn = createTranslator({ locale: "en", messages: { web: en }, namespace: "web" });

  it("an item page names a skin «скин КС2 (CS2)», a case only «КС2 (CS2)»", () => {
    const price = "134 465 800 сум";
    expect(
      tRu("skins.meta.itemTitle", { name: "AWP | Dragon Lore (Factory New)", price, kind: "skin" }),
    ).toBe(
      "AWP | Dragon Lore (Factory New) — скин КС2 (CS2): купить в Узбекистане за 134 465 800 сум",
    );
    expect(tRu("skins.meta.itemTitleNoPrice", { name: "Recoil Case", kind: "case" })).toBe(
      "Recoil Case — КС2 (CS2): купить в Узбекистане за сумы",
    );
    expect(
      tEn("skins.meta.itemTitle", { name: "AK-47 | Redline", price: "$27", kind: "skin" }),
    ).toBe("AK-47 | Redline — CS2 skin: buy in Uzbekistan for $27");
  });

  it("Russian titles keep «КС2 (CS2)» and add «КС ГО»", () => {
    for (const title of [
      tRu("skins.meta.title"),
      tRu("landing.meta.title"),
      tRu("seoPages.cheap.title"),
      tRu("skins.landing.categoryTitle", { name: "Ножи" }),
      tRu("skins.landing.weaponTitle", { weapon: "AWP" }),
      tRu("sell.seo.title"),
    ]) {
      expect(title).toContain("КС2 (CS2");
      expect(title).toContain("КС ГО");
    }
  });
});
