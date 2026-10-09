import ru from "@csmarket/i18n/locales/ru/web.json";
import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import { itemListLd, skinAbout, skinFaq, skinProductLd, wearFloatRange } from "./skin-seo";

import type { SkinDetail } from "@csmarket/utils/skins";

const t = createTranslator({ locale: "ru", messages: { web: ru }, namespace: "web.skins" });

const ITEM: SkinDetail = {
  slug: "ak-47-slate-battle-scarred",
  name: "AK-47 | Slate (Battle-Scarred)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  skin: "Slate",
  exterior: "BS",
  stattrak: false,
  souvenir: false,
  rarity: "Restricted",
  rarity_color: "#8847ff",
  image_url: "https://community.fastly.steamstatic.com/economy/image/x",
  price_usd: "3.40",
  price_uzs: "40000",
  steam_price_usd: "4.10",
  discount_percent: 17,
  count: 23,
  min_float: "0.00000",
  max_float: "1.00000",
  cheapest: [],
  family: [],
  buy_enabled: false,
  collection: null,
  crates: [],
  description: null,
};

describe("wearFloatRange", () => {
  it("is the wear's band cut to the skin's own range", () => {
    expect(
      wearFloatRange({ ...ITEM, exterior: "FT", min_float: "0.10", max_float: "0.70" }),
    ).toEqual(["0.15", "0.38"]);
    expect(
      wearFloatRange({ ...ITEM, exterior: "FN", min_float: "0.02", max_float: "0.80" }),
    ).toEqual(["0.02", "0.07"]);
    expect(wearFloatRange({ ...ITEM, exterior: null })).toBeNull();
  });
});

describe("skinFaq", () => {
  const DAY = new Date("2026-10-10T08:00:00Z");

  it("answers price, Steam (dated), float, payment and the trade hold", () => {
    const faq = skinFaq(ITEM, t, "ru", DAY);
    const text = faq.map((f) => `${f.question} ${f.answer}`).join("\n");
    expect(faq[0]?.question).toBe("Сколько стоит AK-47 | Slate (Battle-Scarred) в Узбекистане?");
    expect(faq[0]?.answer).toMatch(/40\s000 сум/);
    expect(faq[0]?.answer).toMatch(/23 предложений/);
    expect(text).toMatch(/\$4\.10/);
    expect(text).toMatch(/17\s?%/);
    expect(text).toMatch(/от 0\.45 до 1\.00/);
    expect(text).toMatch(/на 10\.10\.2026/);
    expect(faq).toHaveLength(5);
    // Buying is live (M4a): the payment answer names the methods.
    expect(faq[3]?.question).toBe("Как оплатить AK-47 | Slate (Battle-Scarred) в сумах?");
    expect(faq[3]?.answer).toMatch(/Click, Payme или Uzum/);
    expect(faq[4]?.answer).toMatch(/7 дней/);
  });

  it("writes the Steam price in dollars and cents, as the API's units can carry more", () => {
    const at = (steam: string) =>
      skinFaq({ ...ITEM, steam_price_usd: steam }, t, "ru", DAY)
        .map((f) => f.answer)
        .join("\n");
    expect(at("43.794")).toMatch(/\$43\.79[^\d]/);
    expect(at("4.1")).toMatch(/\$4\.10[^\d]/);
    expect(at("12")).toMatch(/\$12\.00[^\d]/);
  });

  it("does not claim Steam is dearer when it is not, nor a price it does not have", () => {
    const faq = skinFaq(
      { ...ITEM, discount_percent: 0, price_usd: null, price_uzs: null },
      t,
      "ru",
      DAY,
    );
    const text = faq.map((f) => f.answer).join("\n");
    expect(text).not.toMatch(/дешевле/);
    expect(faq.some((f) => f.question.startsWith("Сколько стоит"))).toBe(false);
  });
});

describe("skinProductLd", () => {
  it("offers the cheapest price in soʻm as a single offer", () => {
    const ld = skinProductLd(ITEM, "https://csmarket.uz/item/ak-47-slate-battle-scarred");
    expect(ld?.["@type"]).toBe("Product");
    expect(ld?.name).toBe("AK-47 | Slate (Battle-Scarred)");
    // A single Offer, not an AggregateOffer: the page knows the cheapest price but
    // not the dearest, and Search Console flags an AggregateOffer without highPrice.
    expect(ld?.offers).toEqual(
      expect.objectContaining({
        "@type": "Offer",
        price: 40000,
        priceCurrency: "UZS",
        availability: "https://schema.org/InStock",
      }),
    );
  });

  it("keeps a priced item that sold out valid: an out-of-stock offer, never a bare Product", () => {
    const ld = skinProductLd({ ...ITEM, count: 0 }, "u");
    expect(ld?.offers).toEqual(
      expect.objectContaining({ price: 40000, availability: "https://schema.org/OutOfStock" }),
    );
  });

  it("emits no Product at all without a price", () => {
    expect(skinProductLd({ ...ITEM, price_uzs: null }, "u")).toBeNull();
  });

  it("carries the page's own paragraph as its description", () => {
    expect(skinProductLd(ITEM, "u", "About text.")?.description).toBe("About text.");
    expect(skinProductLd(ITEM, "u")).not.toHaveProperty("description");
  });
});

describe("itemListLd", () => {
  it("lists the shown items in order with their localized URLs", () => {
    const ld = itemListLd("uz", [ITEM, { ...ITEM, slug: "awp-x", name: "AWP | X", phase: "Ruby" }]);
    expect(ld).toEqual({
      "@context": "https://schema.org",
      "@type": "ItemList",
      numberOfItems: 2,
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "AK-47 | Slate (Battle-Scarred)",
          url: "https://csmarket.uz/uz/item/ak-47-slate-battle-scarred",
        },
        {
          "@type": "ListItem",
          position: 2,
          name: "AWP | X Ruby",
          url: "https://csmarket.uz/uz/item/awp-x",
        },
      ],
    });
  });

  it("is null for an empty list (an empty ItemList is invalid)", () => {
    expect(itemListLd("ru", [])).toBeNull();
  });
});

describe("skinAbout", () => {
  const member = (exterior: "FN" | "FT" | "BS", stattrak = false) => ({
    slug: `x-${exterior}-${String(stattrak)}`,
    exterior,
    stattrak,
    souvenir: false,
    price_usd: null,
    price_uzs: null,
    count: 0,
  });

  it("states the weapon, rarity, float range, wears, StatTrak and the price", () => {
    const text = skinAbout(
      { ...ITEM, family: [member("FN"), member("FT"), member("BS"), member("FT", true)] },
      t,
      "ru",
      "Винтовки",
    );
    expect(text).toBe(
      "AK-47 | Slate (Battle-Scarred) — скин для AK-47 в КС2 (CS2). Редкость — Restricted. " +
        "Флоат у этого скина бывает от 0.00 до 1.00. " +
        "Бывает в износе: Прямо с завода, После полевых испытаний, Закалённое в боях. " +
        "Есть версия StatTrak™ со счётчиком убийств. " +
        "На csmarket — от 40\u00a0000 сум: оплата в сумах через Click, Payme или Uzum, " +
        "предмет приходит в Steam как предложение обмена.",
    );
  });

  it("a case: its section, no float or wears, no price sentence without a price", () => {
    const text = skinAbout(
      {
        ...ITEM,
        name: "Recoil Case",
        category: "cases",
        weapon: null,
        exterior: null,
        rarity: null,
        min_float: null,
        max_float: null,
        price_uzs: null,
        price_usd: null,
        family: [],
      },
      t,
      "ru",
      "Кейсы",
    );
    expect(text).toBe("Recoil Case — предмет КС2 (CS2) из раздела «Кейсы».");
  });
});

describe("collection and cases", () => {
  const LORE = {
    ...ITEM,
    collection: "The Phoenix Collection",
    crates: [{ name: "Operation Phoenix Weapon Case", slug: "operation-phoenix-weapon-case" }],
  };

  it("the paragraph names the collection and the case", () => {
    const text = skinAbout(LORE, t, "ru", "Винтовки");
    expect(text).toContain("Входит в коллекцию The Phoenix Collection.");
    expect(text).toContain("Выпадает из кейса Operation Phoenix Weapon Case.");
  });

  it("the FAQ answers which case it drops from, in plural for several", () => {
    const one = skinFaq(LORE, t, "ru", new Date("2026-10-10"));
    expect(one.find((f) => f.question.startsWith("Из какого кейса"))?.answer).toMatch(
      /^Из кейса Operation Phoenix Weapon Case\./,
    );
    const two = skinFaq(
      { ...LORE, crates: [...LORE.crates, { name: "Chroma Case", slug: null }] },
      t,
      "ru",
      new Date("2026-10-10"),
    );
    expect(two.find((f) => f.question.startsWith("Из какого кейса"))?.answer).toMatch(
      /^Из кейсов Operation Phoenix Weapon Case, Chroma Case\./,
    );
    expect(skinFaq(ITEM, t, "ru").some((f) => f.question.startsWith("Из какого кейса"))).toBe(
      false,
    );
  });
});
