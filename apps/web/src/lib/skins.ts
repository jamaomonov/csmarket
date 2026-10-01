/**
 * Catalogue data for the storefront. Server helpers (`get*`) read through Next's data
 * cache and follow ruling Q10: `null` only for an API 404, a throw for anything else —
 * an outage is an error page, never a «not found». Browser fetchers (`fetch*`) go through
 * the M1 session client, anonymously. The API is locale-free: no `Accept-Language`, no
 * locale parameter, one cache entry per URL.
 */

import { formatUzs } from "@csmarket/utils/skins";

import type {
  SkinDetail,
  SkinFacets,
  SkinListings,
  SkinQuery,
  SkinSlugs,
  SkinsPage,
  SkinSuggest,
} from "@csmarket/utils/skins";

import { session } from "@/lib/api";
import { apiGet, apiGetOrNull } from "@/lib/server-api";

/** The API's query string for a catalogue query (`min`/`max` are `min_uzs`/`max_uzs` there). */
function catalogParams(q: SkinQuery): string {
  const p = new URLSearchParams();
  if (q.category) p.set("category", q.category);
  if (q.weapon) p.set("weapon", q.weapon);
  if (q.exterior) p.set("exterior", q.exterior);
  if (q.rarity) p.set("rarity", q.rarity);
  if (q.team) p.set("team", q.team);
  if (q.stattrak) p.set("stattrak", "true");
  if (q.q) p.set("q", q.q);
  if (q.minUzs !== undefined) p.set("min_uzs", String(q.minUzs));
  if (q.maxUzs !== undefined) p.set("max_uzs", String(q.maxUzs));
  p.set("sort", q.sort);
  if (q.cursor) p.set("cursor", q.cursor);
  return p.toString();
}

/** One catalogue page. Throws on any failure (ruling Q10). */
export function getSkinsPage(query: SkinQuery): Promise<SkinsPage> {
  return apiGet<SkinsPage>(`/skins/catalog?${catalogParams(query)}`);
}

/** Facet counts, inside a category when one is given. `null` only when the API says 404. */
export function getSkinFacets(category?: string): Promise<SkinFacets | null> {
  const qs = category ? `?${new URLSearchParams({ category }).toString()}` : "";
  return apiGetOrNull<SkinFacets>(`/skins/facets${qs}`);
}

/**
 * One item with its family and cheapest stored offers. `null` only when the API says 404.
 * Not data-cached: an item page is cheap, and hiding an item (admin) must 404 it at once.
 */
export function getSkinDetail(slug: string): Promise<SkinDetail | null> {
  return apiGetOrNull<SkinDetail>(`/skins/${encodeURIComponent(slug)}`, { noStore: true });
}

/** A page of item slugs for the sitemap. */
export function fetchSkinSlugs(offset: number, limit: number): Promise<SkinSlugs> {
  const qs = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return apiGet<SkinSlugs>(`/skins/seo/slugs?${qs.toString()}`, { revalidate: 3600 });
}

/** Browser: the next catalogue page (load more, filter changes). */
export function fetchSkinsPage(query: SkinQuery, signal?: AbortSignal): Promise<SkinsPage> {
  return session.apiGet<SkinsPage>(`/api/v1/skins/catalog?${catalogParams(query)}`, {
    anonymous: true,
    ...(signal ? { signal } : {}),
  });
}

/** Browser: search-box suggestions. */
export function fetchSuggest(q: string, signal?: AbortSignal): Promise<SkinSuggest> {
  const qs = new URLSearchParams({ q });
  return session.apiGet<SkinSuggest>(`/api/v1/skins/suggest?${qs.toString()}`, {
    anonymous: true,
    ...(signal ? { signal } : {}),
  });
}

/** Browser: live offers for an item (the API degrades to the stored snapshot itself). */
export function fetchSkinListings(slug: string, signal?: AbortSignal): Promise<SkinListings> {
  return session.apiGet<SkinListings>(`/api/v1/skins/${encodeURIComponent(slug)}/listings`, {
    anonymous: true,
    ...(signal ? { signal } : {}),
  });
}

/**
 * The price to show: soʻm when the item has one, `$usd` while there is no rate, `null`
 * when it has neither (nothing on sale).
 */
export function displayPrice(
  locale: string,
  uzs: string | null,
  usd: string | null,
): string | null {
  if (uzs !== null) return formatUzs(locale, uzs);
  if (usd !== null) return `$${usd}`;
  return null;
}
