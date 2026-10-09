/**
 * What search engines read on a CS2 item page, built from the item's own numbers: the FAQ
 * (price in soʻm and offers, Steam's price when ours is lower, the wear's float range) and
 * how to pay in soʻm, Steam's trade hold) and the Product JSON-LD with a single Offer in soʻm.
 * Only facts the item has are stated — no price, no price question; not cheaper than Steam, no
 * Steam answer — and a price comparison carries its date.
 */

import type { Exterior, SkinDetail, SkinItem } from "@csmarket/utils/skins";

import { itemPath } from "@/lib/paths";
import { localeUrl } from "@/lib/seo";
import { displayPrice } from "@/lib/skins";

/** Steam's float bands per wear. */
const WEAR_BANDS: Record<Exterior, [number, number]> = {
  FN: [0, 0.07],
  MW: [0.07, 0.15],
  FT: [0.15, 0.38],
  WW: [0.38, 0.45],
  BS: [0.45, 1],
};

/** The float an item of this wear can have: the wear's band cut to the skin's range. */
export function wearFloatRange(
  item: Pick<SkinDetail, "exterior" | "min_float" | "max_float">,
): [string, string] | null {
  if (!item.exterior) return null;
  const [lo, hi] = WEAR_BANDS[item.exterior];
  const min = Math.max(lo, item.min_float === null ? lo : Number(item.min_float));
  const max = Math.min(hi, item.max_float === null ? hi : Number(item.max_float));
  if (!(min < max)) return null;
  return [min.toFixed(2), max.toFixed(2)];
}

/** The name as the page shows it, Doppler phase included. */
export function skinFullName(item: Pick<SkinDetail, "name" | "phase">): string {
  return item.phase ? `${item.name} ${item.phase}` : item.name;
}

export interface FaqEntry {
  question: string;
  answer: string;
}

/** The `web.skins` keys the FAQ reads. */
type FaqKey =
  | "faq.priceQ"
  | "faq.priceA"
  | "faq.steamQ"
  | "faq.steamA"
  | "faq.floatQ"
  | "faq.floatA"
  | "faq.payQ"
  | "faq.payA"
  | "faq.holdQ"
  | "faq.holdA"
  | `exterior.${Exterior}`;

/** A `next-intl` translator scoped to `web.skins` — any that knows the FAQ's keys. */
export type SkinsT = (key: FaqKey, values?: Record<string, string | number>) => string;

/** «10.10.2026» (ru / uz) or «10 Oct 2026» (en), in Tashkent: the date a price claim holds. */
export function claimDate(locale: string, day: Date): string {
  return locale === "en"
    ? new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "Asia/Tashkent",
      }).format(day)
    : new Intl.DateTimeFormat("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        timeZone: "Asia/Tashkent",
      }).format(day);
}

export function skinFaq(
  item: SkinDetail,
  t: SkinsT,
  locale: string,
  day: Date = new Date(),
): FaqEntry[] {
  const name = skinFullName(item);
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  const out: FaqEntry[] = [];
  if (price !== null && item.count > 0) {
    out.push({
      question: t("faq.priceQ", { name }),
      answer: t("faq.priceA", { name, price, count: item.count }),
    });
  }
  if (item.steam_price_usd && item.discount_percent && item.discount_percent > 0) {
    out.push({
      question: t("faq.steamQ", { name }),
      answer: t("faq.steamA", {
        // The API keeps Waxpeer's tenths of a cent ("43.794"); a price reads in cents.
        steam: Number(item.steam_price_usd).toFixed(2),
        percent: item.discount_percent,
        // A price comparison always carries its date (copy rules).
        date: claimDate(locale, day),
      }),
    });
  }
  const range = wearFloatRange(item);
  if (range && item.exterior) {
    out.push({
      question: t("faq.floatQ", { name }),
      answer: t("faq.floatA", {
        exterior: t(`exterior.${item.exterior}`),
        min: range[0],
        max: range[1],
      }),
    });
  }
  out.push(
    { question: t("faq.payQ", { name }), answer: t("faq.payA") },
    { question: t("faq.holdQ", { name }), answer: t("faq.holdA") },
  );
  return out;
}

export interface ProductLd {
  "@context": "https://schema.org";
  "@type": "Product";
  name: string;
  image?: string;
  category: string;
  url: string;
  offers: {
    "@type": "Offer";
    price: number;
    priceCurrency: "UZS";
    availability: string;
    url: string;
    priceValidUntil: string;
  };
}

/**
 * The item's Product JSON-LD, or `null` when it has no price — a Product with no
 * offer, review or rating is invalid for Google and is reported as an error.
 *
 * A single Offer at our cheapest price rather than an AggregateOffer: the page
 * knows the lowest price but not the highest, and an AggregateOffer without
 * `highPrice` is flagged in Search Console. A priced item that has sold out keeps
 * its Offer, marked out of stock.
 */
export function skinProductLd(item: SkinDetail, url: string): ProductLd | null {
  if (item.price_uzs === null) return null;
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: skinFullName(item),
    ...(item.image_url ? { image: item.image_url } : {}),
    category: `CS2 ${item.weapon ?? item.category}`,
    url,
    offers: {
      "@type": "Offer",
      price: Math.round(Number(item.price_uzs)),
      priceCurrency: "UZS",
      availability: item.count > 0 ? "https://schema.org/InStock" : "https://schema.org/OutOfStock",
      url,
      // Prices follow a five-minute sync; a short, rolling window keeps the claim true.
      priceValidUntil: new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10),
    },
  };
}

export interface ItemListLd {
  "@context": "https://schema.org";
  "@type": "ItemList";
  numberOfItems: number;
  itemListElement: { "@type": "ListItem"; position: number; name: string; url: string }[];
}

/**
 * The skins a listing page shows as an ItemList (a summary list: name and URL, each item's
 * own page carries its Product). `null` for an empty page, which would be invalid.
 */
export function itemListLd(
  locale: string,
  items: Pick<SkinItem, "slug" | "name" | "phase">[],
): ItemListLd | null {
  if (items.length === 0) return null;
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    numberOfItems: items.length,
    itemListElement: items.map((it, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: skinFullName(it),
      url: localeUrl(locale, itemPath(it.slug)),
    })),
  };
}

/** The `web.skins` keys the «О предмете» paragraph reads. */
type AboutKey =
  | "about.weapon"
  | "about.item"
  | "about.rarity"
  | "about.float"
  | "about.wears"
  | "about.stattrak"
  | "about.souvenir"
  | "about.buy"
  | `exterior.${Exterior}`;

export type AboutT = (key: AboutKey, values?: Record<string, string | number>) => string;

/**
 * «О предмете»: a paragraph written from the item's own facts — what it is, its rarity, the
 * skin's float range, the wears and variants it comes in, and the price — so every item page
 * carries text of its own. A fact the item lacks is left out, never guessed.
 */
export function skinAbout(
  item: SkinDetail,
  t: AboutT,
  locale: string,
  categoryName: string,
): string {
  const name = skinFullName(item);
  const out = [
    item.weapon
      ? t("about.weapon", { name, weapon: item.weapon })
      : t("about.item", { name, category: categoryName }),
  ];
  if (item.rarity) out.push(t("about.rarity", { rarity: item.rarity }));
  if (item.exterior && item.min_float !== null && item.max_float !== null) {
    out.push(
      t("about.float", {
        min: Number(item.min_float).toFixed(2),
        max: Number(item.max_float).toFixed(2),
      }),
    );
  }
  const wears = [...new Set(item.family.flatMap((m) => (m.exterior ? [m.exterior] : [])))];
  if (wears.length > 1) {
    out.push(t("about.wears", { list: wears.map((w) => t(`exterior.${w}`)).join(", ") }));
  }
  if (!item.stattrak && item.family.some((m) => m.stattrak)) out.push(t("about.stattrak"));
  if (!item.souvenir && item.family.some((m) => m.souvenir)) out.push(t("about.souvenir"));
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  if (price !== null && item.count > 0) out.push(t("about.buy", { price }));
  return out.join(" ");
}
