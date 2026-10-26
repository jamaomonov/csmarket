import { LOCALES } from "@csmarket/i18n";

import type { ArticleLocales, ArticleSitemapEntry } from "@/lib/articles";

import { SECTIONS, sectionHref } from "@/lib/articles";
import { articlePath } from "@/lib/paths";
import { localeUrl } from "@/lib/seo";
import { today } from "@/lib/skins-sitemap";

const escapeXml = (s: string): string =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const alternate = (hreflang: string, href: string): string =>
  `<xhtml:link rel="alternate" hreflang="${hreflang}" href="${escapeXml(href)}"/>`;

/** One `<url>` per live locale of `path`, each naming only the live locales as alternates. */
function urls(path: string, live: string[], lastmod: string): string[] {
  const links = [
    ...LOCALES.filter((l) => live.includes(l)).map((l) => alternate(l, localeUrl(l, path))),
    ...(live.includes("ru") ? [alternate("x-default", localeUrl("ru", path))] : []),
  ].join("");
  return LOCALES.filter((l) => live.includes(l)).map(
    (l) =>
      `<url><loc>${escapeXml(localeUrl(l, path))}</loc><lastmod>${lastmod}</lastmod>${links}</url>`,
  );
}

/**
 * `/skins-sitemap/articles.xml`: every live translation (its own lastmod), the «Статьи» list and
 * each section list in the languages where they have articles. A translation that does not exist
 * answers 404, so it is never listed or named as an alternate.
 */
export function articlesXml(entries: ArticleSitemapEntry[], sections: ArticleLocales): string {
  const bySlug = new Map<string, { live: string[]; lastmod: string }>();
  for (const e of entries) {
    const found = bySlug.get(e.slug) ?? { live: [], lastmod: "" };
    found.live.push(e.locale);
    const day = e.updated_at.slice(0, 10);
    if (day > found.lastmod) found.lastmod = day;
    bySlug.set(e.slug, found);
  }
  const lists = Object.entries(sections);
  const all = lists.filter(([, s]) => s.length > 0).map(([l]) => l);
  const body = [
    ...urls(sectionHref(null), all, today()),
    ...SECTIONS.flatMap((s) =>
      urls(
        sectionHref(s),
        lists.filter(([, live]) => live.includes(s)).map(([l]) => l),
        today(),
      ),
    ),
    ...[...bySlug].flatMap(([slug, { live, lastmod }]) => urls(articlePath(slug), live, lastmod)),
  ];
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ...body,
    "</urlset>",
  ].join("\n");
}
