import { getTranslations } from "next-intl/server";

import type { ArticleLocales, Section } from "@/lib/articles";
import type { Metadata } from "next";

import { sectionHref } from "@/lib/articles";
import { fetchArticleLocales } from "@/lib/articles-server";
import {
  alternatesFor,
  GEO_META,
  localeUrl,
  NOINDEX_FOLLOW,
  ogLocale,
  ROBOTS,
  shareImage,
} from "@/lib/seo";

/** The locales whose list (all, or one section) has at least one live article. */
export function listLocales(sections: ArticleLocales, section: Section | null): string[] {
  return Object.entries(sections)
    .filter(([, live]) => (section === null ? live.length > 0 : live.includes(section)))
    .map(([locale]) => locale);
}

/**
 * The metadata of «Статьи» or a section list: `noindex` while it is empty in that language and
 * on every «Показать ещё» page (`?cursor=`); hreflang only where the list has articles.
 */
export async function listMetadata(
  locale: string,
  section: Section | null,
  cursor: string | null,
): Promise<Metadata> {
  const t = await getTranslations({ locale, namespace: "web.articles" });
  const live = listLocales(await fetchArticleLocales(), section);
  const title = section ? t(`sectionTitles.${section}`) : t("title");
  const description = section ? t(`sectionDescriptions.${section}`) : t("description");
  const path = sectionHref(section);
  const indexed = cursor === null && live.includes(locale);
  return {
    title,
    description,
    alternates: alternatesFor(locale, path, live),
    robots: indexed ? ROBOTS : NOINDEX_FOLLOW,
    other: GEO_META,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, path),
      ...ogLocale(locale),
      images: shareImage(locale, title).openGraph,
    },
    twitter: shareImage(locale, title).twitter,
  };
}
