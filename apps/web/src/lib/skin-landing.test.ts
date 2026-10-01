import { describe, expect, it } from "vitest";

import { categoryPath, itemPath, weaponPath } from "./paths";
import { countUnit, findWeapon, isSkinCategory, landingPaths, weaponSlug } from "./skin-landing";

const FACETS = {
  categories: [
    { value: "rifles", count: 4148 },
    { value: "knives", count: 3505 },
  ],
  weapons: [
    { value: "AK-47", count: 594 },
    { value: "M4A1-S", count: 405 },
    { value: "Desert Eagle", count: 381 },
    { value: "★ Karambit", count: 120 },
  ],
  exteriors: [],
  rarities: [],
};

describe("skin landings", () => {
  it("slugs a weapon the way people type it", () => {
    expect(weaponSlug("AK-47")).toBe("ak-47");
    expect(weaponSlug("M4A1-S")).toBe("m4a1-s");
    expect(weaponSlug("Desert Eagle")).toBe("desert-eagle");
    expect(weaponSlug("★ Karambit")).toBe("karambit");
  });

  it("finds the weapon behind a slug, or nothing", () => {
    expect(findWeapon(FACETS, "desert-eagle")).toEqual({ value: "Desert Eagle", count: 381 });
    expect(findWeapon(FACETS, "nope")).toBeNull();
  });

  it("lists every category and weapon page", () => {
    expect(landingPaths(FACETS)).toEqual([
      "/category/rifles",
      "/category/knives",
      "/weapon/ak-47",
      "/weapon/m4a1-s",
      "/weapon/desert-eagle",
      "/weapon/karambit",
    ]);
  });

  it("builds locale-less paths", () => {
    expect(itemPath("ak-47-redline-field-tested")).toBe("/item/ak-47-redline-field-tested");
    expect(categoryPath("knives")).toBe("/category/knives");
    expect(weaponPath("ak-47")).toBe("/weapon/ak-47");
  });

  it("knows the categories and the noun a count takes", () => {
    expect(isSkinCategory("music-kits")).toBe(true);
    expect(isSkinCategory("stickers")).toBe(false);
    expect(countUnit("cases")).toBe("cases");
    expect(countUnit("music-kits")).toBe("music");
    expect(countUnit("rifles")).toBe("other");
    expect(countUnit(undefined)).toBe("other");
  });
});
