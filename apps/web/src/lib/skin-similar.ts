/** «Другие скины AK-47» under an item: its neighbours in the catalogue. */
import type { SkinItem } from "@csmarket/utils/skins";

import { isSkinCategory } from "@/lib/skin-landing";
import { getSkinsPage } from "@/lib/skins";

/** Cards in the block. */
export const SIMILAR = 10;

/**
 * Other skins of the item's weapon (or items of its section), popular first, one card per
 * skin, without the item's own family. Advisory — an API failure leaves the block out, never the page.
 */
export async function similarSkins(
  item: Pick<SkinItem, "slug" | "skin" | "weapon" | "category">,
): Promise<SkinItem[]> {
  const query = item.weapon
    ? { sort: "popular" as const, weapon: item.weapon }
    : isSkinCategory(item.category)
      ? { sort: "popular" as const, category: item.category }
      : null;
  if (query === null) return [];
  try {
    const page = await getSkinsPage(query);
    // One card per skin (the catalogue lists each wear apart), never the item's own family.
    const seen = new Set<string>(item.skin === null ? [] : [item.skin]);
    const out: SkinItem[] = [];
    for (const it of page.items) {
      const key = it.skin ?? it.slug;
      if (it.slug === item.slug || seen.has(key)) continue;
      seen.add(key);
      out.push(it);
      if (out.length === SIMILAR) break;
    }
    return out;
  } catch {
    return [];
  }
}
