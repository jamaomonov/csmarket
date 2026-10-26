import type {
  Article,
  ArticleLocales,
  ArticleRedirect,
  ArticlesPage,
  ArticleSitemapEntry,
  Section,
} from "@/lib/articles";

import { apiGet, apiGetOrNull } from "@/lib/server-api";

/** Edits show within a minute (ADR-0025): no on-demand revalidation. */
const CACHE = { revalidate: 60, tags: ["articles"] };

export async function fetchArticles(
  locale: string,
  section: Section | null,
  cursor: string | null,
): Promise<ArticlesPage> {
  const q = new URLSearchParams({ locale });
  if (section) q.set("section", section);
  if (cursor) q.set("cursor", cursor);
  return apiGet<ArticlesPage>(`/articles?${q.toString()}`, CACHE);
}

/** The live translation, a redirect for a former slug, or `null` (a real 404). */
export async function fetchArticle(
  slug: string,
  locale: string,
): Promise<Article | ArticleRedirect | null> {
  return apiGetOrNull<Article | ArticleRedirect>(
    `/articles/${encodeURIComponent(slug)}?locale=${locale}`,
    CACHE,
  );
}

const NO_SECTIONS: ArticleLocales = { ru: [], uz: [], en: [] };

/** The sections with a live article per locale; none when the API cannot say. */
export async function fetchArticleLocales(): Promise<ArticleLocales> {
  try {
    return await apiGet<ArticleLocales>("/articles/locales", CACHE);
  } catch {
    return NO_SECTIONS;
  }
}

export async function fetchArticleSitemap(): Promise<ArticleSitemapEntry[]> {
  return (await apiGet<{ items: ArticleSitemapEntry[] }>("/articles/sitemap", CACHE)).items;
}
