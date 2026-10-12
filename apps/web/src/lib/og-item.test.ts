import { describe, expect, it } from "vitest";

import {
  fitTitle,
  itemOgModel,
  itemOgUrl,
  ogRarityColor,
  textWidth,
  TITLE_MAX_WIDTH,
  wrapWords,
} from "./og-item";

import type { SkinItem } from "@csmarket/utils/skins";

const base: SkinItem = {
  slug: "awp-dragon-lore-mw",
  name: "AWP | Dragon Lore (Minimal Wear)",
  phase: null,
  category: "rifles",
  weapon: "AWP",
  skin: "Dragon Lore",
  exterior: "MW",
  stattrak: false,
  souvenir: false,
  rarity: "Covert",
  rarity_color: "#eb4b4b",
  image_url: null,
  price_usd: "1",
  price_uzs: "12000",
  steam_price_usd: null,
  discount_percent: null,
  count: 1,
  min_float: null,
  max_float: null,
};

const labels = {
  vanilla: "Ванильный",
  category: "Винтовки",
  exterior: (e: string) => `ext:${e}`,
};

describe("itemOgUrl", () => {
  it("names the locale even for ru and ends in .png", () => {
    expect(itemOgUrl("ru", "ak-47-redline-ft")).toBe(
      "https://csmarket.uz/ru/item/ak-47-redline-ft/og.png",
    );
    expect(itemOgUrl("en", "a b")).toBe("https://csmarket.uz/en/item/a%20b/og.png");
  });
});

describe("ogRarityColor", () => {
  it("keeps a hex colour, falls back to Mil-Spec blue otherwise", () => {
    expect(ogRarityColor("#eb4b4b")).toBe("#eb4b4b");
    expect(ogRarityColor(null)).toBe("#4b69ff");
    expect(ogRarityColor("red; background:url(x)")).toBe("#4b69ff");
  });
});

describe("fitTitle", () => {
  it("a short name is one line, as big as it fits, upper case", () => {
    expect(fitTitle("Redline")).toEqual({ lines: ["REDLINE"], fontSize: 96 });
    expect(fitTitle("Dragon Lore")).toEqual({ lines: ["DRAGON LORE"], fontSize: 84 });
  });

  it("a long name shrinks and wraps to two lines that fit", () => {
    const fit = fitTitle("Sir Bloody Miami Darryl | The Professionals");
    expect(fit.lines.length).toBeLessThanOrEqual(2);
    expect(fit.fontSize).toBeLessThan(96);
    for (const l of fit.lines) expect(textWidth(l, fit.fontSize)).toBeLessThanOrEqual(600);
  });

  it("never more than three lines; an overlong one ends in an ellipsis", () => {
    const fit = fitTitle(Array.from({ length: 30 }, () => "Holo").join(" "));
    expect(fit.fontSize).toBe(40);
    expect(fit.lines).toHaveLength(3);
    expect(fit.lines[2]?.endsWith("…")).toBe(true);
    for (const l of fit.lines) expect(textWidth(l, 40)).toBeLessThanOrEqual(TITLE_MAX_WIDTH);
  });

  it("a single word too long for a line is cut, not overflowing", () => {
    const fit = fitTitle("A".repeat(60));
    for (const l of fit.lines) expect(textWidth(l, fit.fontSize)).toBeLessThanOrEqual(600);
  });
});

describe("wrapWords", () => {
  it("wraps greedily", () => {
    expect(wrapWords("AA BB CC", 10, textWidth("AA BB", 10))).toEqual(["AA BB", "CC"]);
  });
});

describe("itemOgModel", () => {
  it("a weapon skin: weapon over the skin, souvenir and the wear below, rarity glow", () => {
    const m = itemOgModel({ ...base, souvenir: true }, labels);
    expect(m.kicker).toBe("AWP");
    expect(m.star).toBe(false);
    expect(m.title.lines).toEqual(["DRAGON LORE"]);
    expect(m.tags.map((t) => t.label)).toEqual(["Souvenir", "ext:MW"]);
    expect(m.tags[1]?.dot).toBeDefined();
    expect(m.glow).toBe("#eb4b4b");
    expect(m.rarity).toEqual({ name: "Covert", color: "#eb4b4b" });
  });

  it("a StatTrak knife with a phase gets the star and the phase tag", () => {
    const m = itemOgModel(
      {
        ...base,
        name: "★ StatTrak™ Karambit | Doppler (Factory New)",
        category: "knives",
        weapon: "★ Karambit",
        skin: "Doppler",
        phase: "Phase 2",
        exterior: "FN",
        stattrak: true,
      },
      labels,
    );
    expect(m.kicker).toBe("Karambit");
    expect(m.star).toBe(true);
    expect(m.tags.map((t) => t.label)).toEqual(["StatTrak™", "Phase 2", "ext:FN"]);
  });

  it("a vanilla knife is titled in the page's word for it", () => {
    const m = itemOgModel(
      {
        ...base,
        name: "★ Karambit",
        category: "knives",
        weapon: "Karambit",
        skin: null,
        exterior: null,
      },
      labels,
    );
    expect(m.title.lines).toEqual(["ВАНИЛЬНЫЙ"]);
    expect(m.star).toBe(true);
    expect(m.tags).toEqual([]);
  });

  it("a sticker: the type over the rest of the name", () => {
    const m = itemOgModel(
      {
        ...base,
        name: "Sticker | Natus Vincere (Holo) | Paris 2023",
        category: "stickers",
        weapon: null,
        skin: null,
        exterior: null,
        rarity: null,
        rarity_color: null,
      },
      { ...labels, category: null },
    );
    expect(m.kicker).toBe("Sticker");
    expect(m.title.lines.join(" ")).toBe("NATUS VINCERE (HOLO) | PARIS 2023");
    expect(m.rarity).toBeNull();
    expect(m.glow).toBe("#4b69ff");
  });

  it("an agent or a case: the category over the full name", () => {
    const m = itemOgModel(
      {
        ...base,
        name: "Kilowatt Case",
        category: "cases",
        weapon: null,
        skin: null,
        exterior: null,
      },
      { ...labels, category: "Кейсы" },
    );
    expect(m.kicker).toBe("Кейсы");
    expect(m.title.lines).toEqual(["KILOWATT CASE"]);
  });

  it("an untranslated category without a type prefix falls back to CS2", () => {
    const m = itemOgModel(
      { ...base, name: "Pin | x", category: "collectibles", weapon: null, skin: null },
      { ...labels, category: null },
    );
    expect(m.kicker).toBe("CS2");
  });

  it("a StatTrak music kit keeps the marker as a tag, the kicker says Music Kit", () => {
    const m = itemOgModel(
      {
        ...base,
        name: "StatTrak™ Music Kit | Daniel Sadowski, Crimson Assault",
        category: "music-kits",
        weapon: null,
        skin: null,
        exterior: null,
        stattrak: true,
      },
      labels,
    );
    expect(m.kicker).toBe("Music Kit");
    expect(m.tags.map((t) => t.label)).toEqual(["StatTrak™"]);
  });
});
