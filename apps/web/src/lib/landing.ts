/**
 * The landing's data, composed from ordinary catalogue queries (spec 2026-10-09 SEO landing
 * §2): a curated hero showcase, popular tabs, category tiles and the stats strip. Every read
 * is cached like the market's and never throws: an API outage renders an empty block, not a
 * broken landing.
 */
import { unstable_cache } from "next/cache";

import type { SkinFacets, SkinItem, SkinsPage } from "@csmarket/utils/skins";

import { apiGet } from "@/lib/server-api";

/** Seconds the landing's catalogue reads are cached. */
const REVALIDATE = 300;

/** A catalogue query: the API's own params (`category`, `q`, `sort`, `max_uzs`, `limit`). */
type CatalogParams = Record<string, string>;

/** The hero showcase, in order: striking skins people search for. Edited here. */
export const HERO_QUERIES: CatalogParams[] = [
  { category: "knives", q: "Karambit Fade" },
  { category: "gloves", q: "Sport Gloves Vice" },
  { category: "rifles", q: "AK-47 Fire Serpent" },
  { category: "knives", q: "M9 Bayonet Gamma Doppler" },
  { category: "rifles", q: "AWP Asiimov" },
];
/** Below this many showcase items, the dearest knives fill in. */
export const HERO_MIN = 3;

export type PopularTab = "popular" | "knives" | "gloves" | "cheap";
export const POPULAR_TABS: PopularTab[] = ["popular", "knives", "gloves", "cheap"];
/** Cards per popular tab. */
export const POPULAR_SIZE = 12;
/** «До 100 000 сум». */
export const CHEAP_MAX_UZS = 100_000;
/** «Популярное» mixes these (cases, keys and charms stay out of the showcase). */
const POPULAR_MIX = ["rifles", "knives", "gloves", "pistols", "smgs"] as const;
/** «До 100 000 сум» mixes weapon skins only. */
const CHEAP_MIX = ["rifles", "pistols", "smgs"] as const;

/** Category tiles: two large, the rest small. */
export const BIG_TILES = ["knives", "gloves"] as const;
export const SMALL_TILES = [
  "rifles",
  "pistols",
  "smgs",
  "heavy",
  "cases",
  "agents",
  "charms",
  "keys",
] as const;

export interface CategoryTile {
  category: string;
  /** A real skin of the category for the picture. */
  item: SkinItem | null;
  /** The category's lowest price, whole soʻm as digits. */
  fromUzs: string | null;
  count: number;
}

export interface LandingStats {
  /** Items on sale across every category. */
  inStock: number;
  /** The cheapest item on sale, whole soʻm as digits. */
  fromUzs: string | null;
}

async function catalog(params: CatalogParams, limit: number): Promise<SkinItem[]> {
  const qs = new URLSearchParams({ sort: "popular", ...params, limit: String(limit) });
  try {
    const page = await apiGet<SkinsPage>(`/skins/catalog?${qs.toString()}`, {
      revalidate: REVALIDATE,
    });
    return page.items;
  } catch {
    return [];
  }
}

/** The hero showcase: the curated queries' first hits, topped up with the dearest knives. */
export async function getHero(): Promise<SkinItem[]> {
  const found = await Promise.all(HERO_QUERIES.map((q) => catalog(q, 1)));
  const items = found.flatMap((hits) => hits.slice(0, 1));
  if (items.length >= HERO_MIN) return items;
  const knives = await catalog({ category: "knives", sort: "-price" }, HERO_QUERIES.length);
  const seen = new Set(items.map((i) => i.slug));
  return [...items, ...knives.filter((k) => !seen.has(k.slug))].slice(0, HERO_QUERIES.length);
}

/** Round-robin the lists so «Популярное» shows a knife, a rifle, gloves… in turn. */
function interleave(lists: SkinItem[][], size: number): SkinItem[] {
  const out: SkinItem[] = [];
  for (let i = 0; out.length < size && lists.some((l) => i < l.length); i++) {
    for (const list of lists) {
      const item = list[i];
      if (item !== undefined && out.length < size) out.push(item);
    }
  }
  return out;
}

/** One popular tab's cards. */
export async function getPopular(tab: PopularTab): Promise<SkinItem[]> {
  switch (tab) {
    case "popular": {
      const per = Math.ceil(POPULAR_SIZE / POPULAR_MIX.length) + 1;
      const lists = await Promise.all(POPULAR_MIX.map((c) => catalog({ category: c }, per)));
      return interleave(lists, POPULAR_SIZE);
    }
    case "knives":
    case "gloves":
      return catalog({ category: tab }, POPULAR_SIZE);
    case "cheap": {
      const per = Math.ceil(POPULAR_SIZE / CHEAP_MIX.length) + 1;
      const max = String(CHEAP_MAX_UZS);
      const lists = await Promise.all(
        CHEAP_MIX.map((c) => catalog({ category: c, max_uzs: max }, per)),
      );
      return interleave(lists, POPULAR_SIZE);
    }
    default: {
      const never: never = tab;
      return never;
    }
  }
}

async function facets(): Promise<SkinFacets | null> {
  try {
    return await apiGet<SkinFacets>("/skins/facets", { revalidate: REVALIDATE });
  } catch {
    return null;
  }
}

/** The category tiles: a real skin for the picture and the lowest price of each. */
export async function getCategoryTiles(): Promise<CategoryTile[]> {
  const counts = new Map((await facets())?.categories.map((c) => [c.value, c.count]) ?? []);
  const all = [...BIG_TILES, ...SMALL_TILES];
  return Promise.all(
    all.map(async (category) => {
      const [top, cheapest] = await Promise.all([
        catalog({ category }, 1),
        catalog({ category, sort: "price" }, 1),
      ]);
      return {
        category,
        item: top[0] ?? null,
        fromUzs: cheapest[0]?.price_uzs ?? null,
        count: counts.get(category) ?? 0,
      };
    }),
  );
}

/** The stats strip: only figures the catalogue backs. */
export async function getStats(): Promise<LandingStats> {
  const [f, cheapest] = await Promise.all([facets(), catalog({ sort: "price" }, 1)]);
  const inStock = f?.categories.reduce((sum, c) => sum + c.count, 0) ?? 0;
  return { inStock, fromUzs: cheapest[0]?.price_uzs ?? null };
}

export interface LandingData {
  hero: SkinItem[];
  tiles: CategoryTile[];
  stats: LandingStats;
  popular: Record<PopularTab, SkinItem[]>;
}

/** Every block of the landing in one pass (uncached; the page reads `getLandingData`). */
export async function loadLanding(): Promise<LandingData> {
  const [hero, tiles, stats, ...lists] = await Promise.all([
    getHero(),
    getCategoryTiles(),
    getStats(),
    ...POPULAR_TABS.map((tab) => getPopular(tab)),
  ]);
  const popular = Object.fromEntries(POPULAR_TABS.map((tab, i) => [tab, lists[i] ?? []]));
  return { hero, tiles, stats, popular: popular as Record<PopularTab, SkinItem[]> }; // every tab set
}

/** Cards on the hero wall: three columns of six. */
export const WALL_SIZE = 18;

/**
 * The hero wall: the curated showcase first, then knives, gloves and popular skins in turn —
 * one card per slug, only items with a picture and a price.
 */
export function wallItems(
  data: Pick<LandingData, "hero" | "popular">,
  size: number = WALL_SIZE,
): SkinItem[] {
  const { knives, gloves, popular } = data.popular;
  const mixed: SkinItem[] = [...data.hero];
  for (let i = 0; i < Math.max(knives.length, gloves.length, popular.length); i++) {
    for (const list of [knives, gloves, popular]) {
      const it = list[i];
      if (it !== undefined) mixed.push(it);
    }
  }
  const seen = new Set<string>();
  const out: SkinItem[] = [];
  for (const it of mixed) {
    if (seen.has(it.slug) || it.image_url === null || it.price_uzs === null) continue;
    seen.add(it.slug);
    out.push(it);
    if (out.length === size) break;
  }
  return out;
}

/** One cache entry; throws on an outage (no facets) so an empty landing is never stored. */
const cachedLanding = unstable_cache(
  async () => {
    const data = await loadLanding();
    if (data.stats.inStock === 0) throw new Error("landing: catalogue unavailable");
    return data;
  },
  ["landing-data"],
  { revalidate: REVALIDATE, tags: ["skins"] },
);

/**
 * The landing's data as one cache entry for {@link REVALIDATE} seconds: a warm render reads one
 * entry instead of some thirty catalogue fetches. During an outage it renders the empty blocks
 * uncached, so the landing fills again as soon as the API answers.
 */
export async function getLandingData(): Promise<LandingData> {
  try {
    return await cachedLanding();
  } catch {
    return loadLanding();
  }
}

/**
 * The support channel, read on the server at request time from `CSMARKET_TELEGRAM_URL` (owner,
 * 2026-10-09: «оставь пустым, позже дам»); empty hides its links.
 */
export function telegramUrl(): string {
  const url = process.env.CSMARKET_TELEGRAM_URL ?? "";
  return url.startsWith("https://") ? url : "";
}

/** Profiles for `Organization.sameAs`: `CSMARKET_SOCIAL_URLS`, comma-separated https URLs. */
export function socialUrls(): string[] {
  return (process.env.CSMARKET_SOCIAL_URLS ?? "")
    .split(",")
    .map((u) => u.trim())
    .filter((u) => u.startsWith("https://"));
}
