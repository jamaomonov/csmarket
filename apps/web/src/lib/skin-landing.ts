/**
 * Landing pages for the CS2 market: one per category («Ножи КС2») and one per weapon
 * («Скины AK-47») — clean, indexable URLs for what people search, where the filtered
 * `/?…` views are `noindex` duplicates of the hub. Weapons come from the catalogue's
 * facets, so a new weapon gets its page without a deploy.
 */

import { SKIN_CATEGORIES } from "@csmarket/utils/skins";

import type { Facet, SkinCategory, SkinFacets } from "@csmarket/utils/skins";

import { categoryPath, colorPath, weaponPath } from "@/lib/paths";

export function isSkinCategory(value: string): value is SkinCategory {
  return (SKIN_CATEGORIES as readonly string[]).includes(value);
}

/** `AK-47` → `ak-47`, `Desert Eagle` → `desert-eagle`, `★ Karambit` → `karambit`. */
export function weaponSlug(weapon: string): string {
  return weapon
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function findWeapon(facets: SkinFacets, slug: string): Facet | null {
  return facets.weapons.find((w) => weaponSlug(w.value) === slug) ?? null;
}

/**
 * A landing with fewer items than this is thin (`/category/keys` with three): it stays
 * `noindex, follow` and out of the sitemap until the catalogue fills it.
 */
export const MIN_LANDING_ITEMS = 10;

export function isThinLanding(count: number): boolean {
  return count < MIN_LANDING_ITEMS;
}

/**
 * Every landing page the facets imply, categories first — for the sitemap. Thin ones are
 * left out; a weapon is judged by its first facet, the one `findWeapon` serves.
 */
export function landingPaths(facets: SkinFacets): string[] {
  const seen = new Set<string>();
  const weapons = facets.weapons.flatMap((w) => {
    const path = weaponPath(weaponSlug(w.value));
    if (seen.has(path)) return [];
    seen.add(path);
    return isThinLanding(w.count) ? [] : [path];
  });
  return [
    ...facets.categories.filter((c) => !isThinLanding(c.count)).map((c) => categoryPath(c.value)),
    ...weapons,
    ...(facets.colors ?? []).filter((c) => !isThinLanding(c.count)).map((c) => colorPath(c.value)),
  ];
}

/** Which noun a landing's count takes (`web.skins.landing.count`): a case is not a skin. */
const COUNT_UNITS: Record<string, string> = {
  cases: "cases",
  keys: "keys",
  agents: "agents",
  charms: "charms",
  "music-kits": "music",
};

export function countUnit(category: string | undefined): string {
  return (category !== undefined ? COUNT_UNITS[category] : undefined) ?? "other";
}

/** Categories whose items are not weapon finishes: the copy says «предмет», not «скин». */
const ITEM_CATEGORIES = new Set([
  "cases",
  "keys",
  "music-kits",
  "charms",
  "stickers",
  "graffiti",
  "patches",
]);

/** The noun a landing's copy uses (`{kind, select, skin {…} other {…}}`). */
export function landingKind(category: string | undefined): "skin" | "item" {
  return category !== undefined && ITEM_CATEGORIES.has(category) ? "item" : "skin";
}
