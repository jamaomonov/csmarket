import { describe, expect, it } from "vitest";

import { demoInventory } from "./sell-demo";

import type { SkinItem } from "@csmarket/utils/skins";

const skin = (i: number, price: string | null): SkinItem => ({
  slug: `s${String(i)}`,
  name: `Item ${String(i)}`,
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  skin: `Skin ${String(i)}`,
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  rarity: "Classified",
  rarity_color: "#d32ce6",
  image_url: `https://img.test/${String(i)}.png`,
  price_usd: "1",
  price_uzs: price,
  steam_price_usd: null,
  discount_percent: null,
  count: 1,
  min_float: null,
  max_float: null,
});

describe("demo inventory (dev only)", () => {
  it("offers 80 % of the catalogue price, rounded to 100 soʻm, priced items only", () => {
    const inv = demoInventory([skin(1, "123456"), skin(2, null)], new Date("2026-10-06T00:00:00Z"));
    expect(inv).toHaveLength(1);
    expect(inv[0]?.priceUzs).toBe(98_800);
    expect(inv[0]?.assetId).toBe("demo-0");
  });

  it("some items are trade-locked for a few days, and very cheap ones refused", () => {
    const items = Array.from({ length: 12 }, (_, i) => skin(i, i === 11 ? "2000" : "500000"));
    const inv = demoInventory(items, new Date("2026-10-06T00:00:00Z"));
    expect(inv.some((x) => x.unavailable?.reason === "tradeLock")).toBe(true);
    expect(inv.find((x) => x.slug === "s11")?.unavailable).toEqual({ reason: "tooCheap" });
  });
});
