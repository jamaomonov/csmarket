/**
 * The sitemaps: ~35 000 item pages in three locales are too many for one file, so
 * `/sitemap.xml` is an index over files of {@link SKINS_PER_SITEMAP} items each
 * (`/skins-sitemap/<n>.xml`) plus one of the landing pages (`/skins-sitemap/landings.xml`).
 * Every URL carries hreflang alternates (ru / uz / en and x-default → ru), as the pages do.
 * `robots.txt` names the index.
 */

import { LOCALES } from "@csmarket/i18n";

import { localeUrl } from "@/lib/seo";
import { SITE } from "@/lib/site";

/** Items per file: ×3 locales stays far under the protocol's 50 000 URLs and 50 MB. */
export const SKINS_PER_SITEMAP = 5000;

export function chunkCount(total: number): number {
  return Math.ceil(total / SKINS_PER_SITEMAP);
}

export function chunkUrl(name: string): string {
  return `${SITE}/skins-sitemap/${name}.xml`;
}

const escapeXml = (s: string): string =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** `YYYY-MM-DD` of today (UTC): a lastmod that moves at most daily stays believable. */
export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

const alternate = (hreflang: string, href: string): string =>
  `<xhtml:link rel="alternate" hreflang="${hreflang}" href="${escapeXml(href)}"/>`;

/** One `<url>` per path × locale, each listing all locales and x-default (ru) as alternates. */
export function urlsetXml(paths: string[], lastmod: string): string {
  const urls = paths.flatMap((path) => {
    const links = [
      ...LOCALES.map((l) => alternate(l, localeUrl(l, path))),
      alternate("x-default", localeUrl("ru", path)),
    ].join("");
    return LOCALES.map(
      (l) =>
        `<url><loc>${escapeXml(localeUrl(l, path))}</loc><lastmod>${lastmod}</lastmod>${links}</url>`,
    );
  });
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ...urls,
    "</urlset>",
  ].join("\n");
}

export function sitemapIndexXml(urls: string[], lastmod: string): string {
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urls.map(
      (u) => `<sitemap><loc>${escapeXml(u)}</loc><lastmod>${lastmod}</lastmod></sitemap>`,
    ),
    "</sitemapindex>",
  ].join("\n");
}

export function xmlResponse(body: string): Response {
  return new Response(body, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
