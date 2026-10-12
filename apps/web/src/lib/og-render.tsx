/**
 * Draws the item share card to a PNG response: the route and the sample script share it.
 */
import { ImageResponse } from "next/og";

import type { OgFont } from "@/lib/og-assets";
import type { ItemOgModel } from "@/lib/og-item";

import { ItemOgCard } from "@/components/og/ItemOgCard";
import { OG_HEIGHT, OG_WIDTH } from "@/lib/og-item";

/**
 * A day at the edge (Cloudflare caches `.png` by default) and in browsers, then a week of
 * stale-while-revalidate: like the page's data, the card is a day old at most.
 */
export const OG_CACHE_CONTROL =
  "public, max-age=86400, s-maxage=86400, stale-while-revalidate=604800";

/** The PNG for an item's card. */
export function itemOgResponse(
  model: ItemOgModel,
  image: string | null,
  fonts: OgFont[],
): Response {
  return new ImageResponse(<ItemOgCard model={model} image={image} />, {
    width: OG_WIDTH,
    height: OG_HEIGHT,
    ...(fonts.length > 0 ? { fonts } : {}),
    headers: { "Cache-Control": OG_CACHE_CONTROL },
  });
}
