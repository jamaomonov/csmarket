/**
 * SEO helpers shared across routes. Every page emits hreflang alternates for the three
 * locales plus x-default (→ ru), an og:locale pair and a geo block pinned to Tashkent.
 */

import { LOCALES } from "@csmarket/i18n";

import type { Metadata } from "next";

import { SITE } from "@/lib/site";

/**
 * Shared robots directives. Beyond index/follow we opt into the largest previews Google
 * allows: full-width image thumbnails and no snippet caps.
 */
export const ROBOTS: Metadata["robots"] = {
  index: true,
  follow: true,
  "max-image-preview": "large",
  "max-snippet": -1,
  "max-video-preview": -1,
};

/** Filtered and paged listings: out of the index, links still followed (ruling Q9). */
export const NOINDEX_FOLLOW: Metadata["robots"] = { index: false, follow: true };

const OG_LOCALE: Record<string, string> = {
  ru: "ru_RU",
  en: "en_US",
  uz: "uz_UZ",
};

/** Absolute URL for a locale + path. ru is the default locale → no prefix. */
export function localeUrl(locale: string, path = ""): string {
  const base = locale === "ru" ? "" : `/${locale}`;
  // "/" and "" both mean the home page: `/en`, never `/en/`.
  const url = `${SITE}${base}${path === "/" ? "" : path}`;
  // The bare apex must carry the canonical trailing slash; every other path stays
  // slash-less, so the /en and /uz homes are unaffected.
  return url === SITE ? `${SITE}/` : url;
}

/** canonical + hreflang alternates (incl. x-default → ru) for a given path. */
export function alternates(
  locale: string,
  path = "",
): { canonical: string; languages: Record<string, string> } {
  const languages: Record<string, string> = {};
  for (const l of LOCALES) languages[l] = localeUrl(l, path);
  languages["x-default"] = localeUrl("ru", path);
  return { canonical: localeUrl(locale, path), languages };
}

export function ogLocale(locale: string): { locale: string; alternateLocale: string[] } {
  return {
    locale: OG_LOCALE[locale] ?? "ru_RU",
    alternateLocale: LOCALES.filter((l) => l !== locale).map((l) => OG_LOCALE[l] ?? "ru_RU"),
  };
}

/** Geo signals for Uzbekistan / Tashkent — emitted via metadata.other. */
export const GEO_META: Record<string, string> = {
  "geo.region": "UZ",
  "geo.placename": "Oʻzbekiston",
  "geo.position": "41.311081;69.240562",
  ICBM: "41.311081, 69.240562",
};
