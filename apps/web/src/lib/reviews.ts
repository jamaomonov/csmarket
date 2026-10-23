/**
 * Reviews (spec 2026-10-23-reviews): wire shapes and calls for `/api/v1/reviews*`, and the
 * rules the prompt follows — good is 4–5 stars, the strip shows once per visit, the modal opens
 * only for a deal that succeeded during this visit.
 */
import { session } from "./api";

export type ReviewKind = "market" | "sale";
export type ReviewLocale = "ru" | "uz" | "en";

/** `DealOut`: the deal the prompt asks about. */
export interface PendingDeal {
  kind: ReviewKind;
  number: string;
  /** The skin's name; a sale's most valuable item. Skin names stay English. */
  title: string;
  image_url: string | null;
  items: number;
  /** When the deal succeeded. */
  done_at: string;
}

/** `MyReviewOut`. */
export interface MyReview {
  rating: number;
  text: string | null;
  locale: string;
  created_at: string;
  updated_at: string;
}

/** `DealReviewOut`. */
export interface DealReview {
  kind: ReviewKind;
  number: string;
  can_review: boolean;
  editable_until: string | null;
  review: MyReview | null;
}

/** `PublicReviewOut`. */
export interface PublicReview {
  id: string;
  author_name: string | null;
  author_avatar_url: string | null;
  rating: number;
  text: string | null;
  kind: ReviewKind;
  skin_name: string | null;
  locale: string;
  created_at: string;
}

/** `PublicReviewsOut`. */
export interface PublicReviews {
  enabled: boolean;
  count: number;
  items: PublicReview[];
  next_cursor: string | null;
}

/** `ReviewIn`. */
export interface ReviewIn {
  rating: number;
  text: string | null;
  locale: ReviewLocale;
}

export const GOOD_FROM = 4;
export const TEXT_MAX = 1000;
/** A deal done this long before the page loaded still counts as «this visit» (clock skew). */
export const LIVE_SKEW_MS = 120_000;
const STRIP_KEY = "csmarket.web.review_strip";
// Where the strip's mark lives when the browser refuses sessionStorage: this page load only.
let stripShownHere = false;

export const REVIEW_PENDING_KEY = ["reviews", "pending"] as const;
export const dealReviewKey = (kind: ReviewKind, number: string) =>
  ["reviews", "deal", kind, number] as const;

export const isGood = (rating: number): boolean => rating >= GOOD_FROM;

const path = (kind: ReviewKind, number: string): string =>
  `/api/v1/reviews/${kind}/${encodeURIComponent(number)}`;

/** `GET /reviews/pending`. */
export function getPendingReview(): Promise<{ deal: PendingDeal | null }> {
  return session.apiGet<{ deal: PendingDeal | null }>("/api/v1/reviews/pending");
}

/** `GET /reviews/{kind}/{number}`. */
export function getDealReview(kind: ReviewKind, number: string): Promise<DealReview> {
  return session.apiGet<DealReview>(path(kind, number));
}

/** `PUT /reviews/{kind}/{number}`. */
export function saveReview(
  kind: ReviewKind,
  number: string,
  body: ReviewIn,
  key: string,
): Promise<DealReview> {
  return session.apiPut<DealReview>(path(kind, number), body, { idempotencyKey: key });
}

/** `POST /reviews/{kind}/{number}/snooze` (204). */
export function snoozeReview(kind: ReviewKind, number: string, key: string): Promise<undefined> {
  return session.api<undefined>(`${path(kind, number)}/snooze`, {
    method: "POST",
    idempotencyKey: key,
  });
}

/** `POST /reviews/{kind}/{number}/dismiss` (204). */
export function dismissReview(kind: ReviewKind, number: string, key: string): Promise<undefined> {
  return session.api<undefined>(`${path(kind, number)}/dismiss`, {
    method: "POST",
    idempotencyKey: key,
  });
}

/** `GET /reviews` — a further page of the public list, without a session. */
export function getPublicReviews(locale: ReviewLocale, cursor: string): Promise<PublicReviews> {
  const q = new URLSearchParams({ locale, cursor });
  return session.apiGet<PublicReviews>(`/api/v1/reviews?${q.toString()}`, { anonymous: true });
}

/** A fresh `Idempotency-Key` for one review action. */
export function mintReviewKey(): string {
  return `web-review-${crypto.randomUUID()}`;
}

export interface LiveCheck {
  /** The deal pending when the page loaded (it gets the strip, not the modal). */
  initialNumber: string | null;
  /** Deals the modal was already opened for in this visit. */
  opened: ReadonlySet<string>;
  visitStartMs: number;
}

/** Open the modal for `deal` now: it succeeded during this visit and was not offered yet. */
export function shouldOpenLive(deal: PendingDeal | null, c: LiveCheck): deal is PendingDeal {
  if (deal === null) return false;
  if (deal.number === c.initialNumber || c.opened.has(deal.number)) return false;
  return Date.parse(deal.done_at) >= c.visitStartMs - LIVE_SKEW_MS;
}

/** The strip's turn: `true` the first time in this tab's session, `false` after. */
export function takeStripTurn(): boolean {
  try {
    if (window.sessionStorage.getItem(STRIP_KEY) !== null) return false;
    window.sessionStorage.setItem(STRIP_KEY, "1");
    return true;
  } catch {
    if (stripShownHere) return false;
    stripShownHere = true;
    return true;
  }
}

/** A sale's picture for its review: the dearest item, then the lowest asset id — the item the
 * prompt shows (`reviews/deals.py`), so the page and the prompt agree. */
export function saleCover<T extends { asset_id: string; price_uzs: string }>(
  items: readonly T[],
): T | undefined {
  let best: T | undefined;
  for (const i of items) {
    const diff = best === undefined ? 1 : Number(i.price_uzs) - Number(best.price_uzs);
    if (diff > 0 || (diff === 0 && best !== undefined && i.asset_id < best.asset_id)) best = i;
  }
  return best;
}
