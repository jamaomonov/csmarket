/** Admin articles API (spec 2026-10-26-articles): `/api/v1/admin/articles*`. Mirrors the API. */
import { session } from "@/lib/api";

export type Section = "news" | "guides" | "tops";
export type ArticleStatus = "draft" | "published";
export type ArticleLocale = "ru" | "uz" | "en";

export interface Media {
  hash: string;
  /** `/media/<hash>.<ext>`: what the Markdown stores; the API serves it under `/api/v1`. */
  url: string;
  width: number;
  height: number;
  content_type: string;
}

export interface TranslationIn {
  title: string;
  description: string;
  cover_alt: string;
  body: string;
  ready: boolean;
}

export interface Translation extends TranslationIn {
  updated_at: string;
}

export interface AdminArticle {
  id: string;
  section: Section;
  slug: string;
  status: ArticleStatus;
  cover: Media | null;
  translations: Record<ArticleLocale, Translation | null>;
  live_locales: ArticleLocale[];
  views: number;
  likes: number;
  published_at: string | null;
  updated_at: string;
  created_at: string;
}

export interface AdminArticleRow {
  id: string;
  section: Section;
  slug: string;
  status: ArticleStatus;
  title: string;
  live_locales: ArticleLocale[];
  views: number;
  likes: number;
  published_at: string | null;
  updated_at: string;
}

export interface ArticleFilter {
  section: Section | "";
  status: ArticleStatus | "";
}

export interface ArticleIn {
  section: Section;
  slug: string;
  cover_hash?: string;
  translations: Partial<Record<ArticleLocale, TranslationIn>>;
}

export type ArticlePatch = Partial<ArticleIn>;

const BASE = "/api/v1/admin/articles";

export async function listArticles(f: ArticleFilter): Promise<AdminArticleRow[]> {
  const q = new URLSearchParams();
  if (f.section !== "") q.set("section", f.section);
  if (f.status !== "") q.set("status", f.status);
  const tail = q.size > 0 ? `?${q.toString()}` : "";
  return (await session.apiGet<{ items: AdminArticleRow[] }>(`${BASE}${tail}`)).items;
}

export function getArticle(id: string): Promise<AdminArticle> {
  return session.apiGet<AdminArticle>(`${BASE}/${encodeURIComponent(id)}`);
}

export function createArticle(body: ArticleIn, key: string): Promise<AdminArticle> {
  return session.apiPost<AdminArticle>(BASE, body, { idempotencyKey: key });
}

export function updateArticle(id: string, body: ArticlePatch, key: string): Promise<AdminArticle> {
  return session.apiPatch<AdminArticle>(`${BASE}/${encodeURIComponent(id)}`, body, {
    idempotencyKey: key,
  });
}

export function publishArticle(id: string, key: string): Promise<AdminArticle> {
  return session.apiPost<AdminArticle>(`${BASE}/${encodeURIComponent(id)}/publish`, null, {
    idempotencyKey: key,
  });
}

export function unpublishArticle(id: string, key: string): Promise<AdminArticle> {
  return session.apiPost<AdminArticle>(`${BASE}/${encodeURIComponent(id)}/unpublish`, null, {
    idempotencyKey: key,
  });
}

/** An image for the cover or the text: the file itself as the body (ADR-0025). */
export function uploadMedia(file: Blob, key: string): Promise<Media> {
  return session.apiPost<Media>(`${BASE}/media`, file, { idempotencyKey: key });
}
