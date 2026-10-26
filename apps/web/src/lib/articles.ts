/**
 * Articles as the API serves them (`/api/v1/articles*`, spec 2026-10-26-articles). A translation
 * the admin has not written answers 404; a former slug answers `kind: "redirect"`.
 */
import type { SkinItem } from "@csmarket/utils/skins";

import { ARTICLES, articlePath } from "@/lib/paths";

export const SECTIONS = ["news", "guides", "tops"] as const;
export type Section = (typeof SECTIONS)[number];

export function isSection(value: string): value is Section {
  return (SECTIONS as readonly string[]).includes(value);
}

export interface ArticleMedia {
  hash: string;
  /** `/media/<hash>.<ext>`, relative to the API's `/api/v1`. */
  url: string;
  width: number;
  height: number;
  content_type: string;
}

export interface ArticleCard {
  slug: string;
  section: Section;
  title: string;
  description: string;
  cover: ArticleMedia;
  cover_alt: string;
  published_at: string;
  views: number;
  likes: number;
}

export interface ArticlesPage {
  items: ArticleCard[];
  next_cursor: string | null;
}

export interface Article extends ArticleCard {
  kind: "article";
  body: string;
  updated_at: string;
  locales: string[];
  embeds: Record<string, SkinItem>;
  related: ArticleCard[];
}

export interface ArticleRedirect {
  kind: "redirect";
  slug: string;
}

/** Per locale, the sections with at least one live article. */
export type ArticleLocales = Record<"ru" | "uz" | "en", Section[]>;

export interface ArticleSitemapEntry {
  slug: string;
  locale: string;
  updated_at: string;
}

export interface ArticleMe {
  likes: number;
  liked: boolean;
  views: number;
}

/** The API path of a media file; the caller prefixes the API origin. */
export function mediaPath(url: string): string {
  return `/api/v1${url}`;
}

/** The list a section tab links to: all articles, or one section. */
export function sectionHref(section: Section | null): string {
  return section === null ? ARTICLES : articlePath(section);
}

/** Whether the path is one article (not the list or a section list). */
export function articleSlugOf(pathname: string): string | null {
  const m = /^\/(?:(?:uz|en)\/)?articles\/([a-z0-9-]+)$/.exec(pathname);
  const slug = m?.[1];
  return slug !== undefined && !isSection(slug) ? slug : null;
}

/**
 * Where the language switcher leads from `pathname` (locale-less, as `usePathname` gives it):
 * the same page, except from an article that has no translation in `target` — then that
 * language's article list, not a 404.
 */
export function switchTarget(
  pathname: string,
  languages: readonly string[],
  target: string,
): string {
  return articleSlugOf(pathname) !== null && !languages.includes(target) ? ARTICLES : pathname;
}

interface HreflangSource {
  querySelectorAll: (
    selector: string,
  ) => ArrayLike<{ getAttribute: (name: string) => string | null }>;
}

/** The languages the current page links to in its `hreflang` alternates (`x-default` aside). */
export function pageLanguages(doc: HreflangSource): string[] {
  return Array.from(doc.querySelectorAll('link[rel="alternate"][hreflang]'))
    .map((l) => l.getAttribute("hreflang") ?? "")
    .filter((l) => l !== "" && l !== "x-default");
}

/** The sections with a live article in `locale` (none for an unknown locale). */
export function sectionsIn(sections: ArticleLocales, locale: string): Section[] {
  return Object.entries(sections).find(([l]) => l === locale)?.[1] ?? [];
}
