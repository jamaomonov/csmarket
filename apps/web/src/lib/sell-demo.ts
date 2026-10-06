import type { SellItem } from "./sell";
import type { SkinItem } from "@csmarket/utils/skins";

/** What the demo offers of the catalogue price. */
const DEMO_SHARE = 0.8;
/** Below this the demo refuses an item (placeholder for the real rule). */
const DEMO_MIN_UZS = 5_000;
const DAY = 86_400_000;

/**
 * A pretend Steam inventory out of catalogue items — **dev only**, to see the sell page
 * before its API exists. Prices are a share of ours; every fifth item is trade-locked for
 * a few days; a very cheap one is refused. Unpriced or imageless items are left out.
 */
export function demoInventory(items: readonly SkinItem[], now: Date): SellItem[] {
  return items.flatMap((s, i) => {
    if (s.price_uzs === null || s.image_url === null) return [];
    const priceUzs = Math.round((Number(s.price_uzs) * DEMO_SHARE) / 100) * 100;
    const locked = i % 5 === 2;
    return [
      {
        assetId: `demo-${String(i)}`,
        slug: s.slug,
        name: s.name,
        category: s.category,
        weapon: s.weapon,
        skin: s.skin,
        exterior: s.exterior,
        stattrak: s.stattrak,
        imageUrl: s.image_url,
        rarityColor: s.rarity_color,
        priceUzs,
        unavailable:
          priceUzs < DEMO_MIN_UZS
            ? { reason: "tooCheap" as const }
            : locked
              ? {
                  reason: "tradeLock" as const,
                  until: new Date(now.getTime() + ((i % 7) + 1) * DAY).toISOString(),
                }
              : null,
      },
    ];
  });
}
