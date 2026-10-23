/** Admin reviews API (spec 2026-10-23-reviews): `/api/v1/admin/reviews*`. Mirrors the API. */
import { session } from "@/lib/api";

export type ReviewTab = "bad" | "all" | "good";
export type ReviewKind = "market" | "sale";
export type ReviewLocale = "ru" | "uz" | "en";

export interface ReviewUser {
  id: string;
  display_name: string | null;
  avatar_url: string | null;
}

export interface AdminReview {
  id: string;
  kind: ReviewKind;
  number: string;
  rating: number;
  text: string | null;
  locale: ReviewLocale;
  hidden: boolean;
  published: boolean;
  user: ReviewUser;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  resolved_by: ReviewUser | null;
  resolved_note: string | null;
}

export interface ReviewsPage {
  items: AdminReview[];
  next_cursor: string | null;
  /** Unresolved bad reviews, whatever the tab and filters. */
  bad_open: number;
}

export interface ReviewSettings {
  reviews_public: boolean;
  published_count: number;
  updated_at: string | null;
  updated_by: ReviewUser | null;
}

export interface ReviewFilter {
  tab: ReviewTab;
  kind: ReviewKind | "";
  locale: ReviewLocale | "";
}

const BASE = "/api/v1/admin/reviews";

export function getReviews(f: ReviewFilter, cursor: string | null): Promise<ReviewsPage> {
  const q = new URLSearchParams({ tab: f.tab });
  if (f.kind !== "") q.set("kind", f.kind);
  if (f.locale !== "") q.set("locale", f.locale);
  if (cursor !== null) q.set("cursor", cursor);
  return session.apiGet<ReviewsPage>(`${BASE}?${q.toString()}`);
}

export const resolveReview = (id: string, note: string, key: string): Promise<AdminReview> =>
  session.apiPost<AdminReview>(
    `${BASE}/${encodeURIComponent(id)}/resolve`,
    { note },
    { idempotencyKey: key },
  );

export const setReviewHidden = (id: string, hidden: boolean, key: string): Promise<AdminReview> =>
  session.apiPost<AdminReview>(
    `${BASE}/${encodeURIComponent(id)}/${hidden ? "hide" : "unhide"}`,
    {},
    { idempotencyKey: key },
  );

export const getReviewSettings = (): Promise<ReviewSettings> =>
  session.apiGet<ReviewSettings>(`${BASE}/settings`);

export const saveReviewSettings = (on: boolean, key: string): Promise<ReviewSettings> =>
  session.apiPut<ReviewSettings>(
    `${BASE}/settings`,
    { reviews_public: on },
    { idempotencyKey: key },
  );
