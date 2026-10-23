# 0023. Reviews of deals

- **Status**: Accepted
- **Date**: 2026-10-23
- **Deciders**: owner
- **Tags**: backend | frontend | data

## Context and problem statement

The owner wants a 1–5 star rating and an optional text after every successful deal — a delivered
order (market) or a paid sale (buy-back) — to help unhappy users fast and, later, to show good
reviews on the site. Spec `docs/superpowers/specs/2026-10-23-reviews-design.md`.

## Decision drivers

- One honest signal per deal; a bad review must reach an admin, never the public page.
- The prompt must appear the moment the deal succeeds, on any page, without a reload.
- «Не сейчас» and × must hold on every device.
- No new dependency, no new external call.

## Considered options

1. **Computed publication, server-side prompts, the existing socket nudges** — one review per deal,
   `published = rating >= 4 AND NOT hidden` computed in every query, `review_prompts` rows,
   the browser re-reads `GET /reviews/pending` on the order socket's `order.changed` /
   `sale.updated`.
2. **A stored `published` flag** — set on write and on hide.
3. **Prompts in `localStorage`** and **a new realtime event `review.due`**.

## Decision outcome

**Chosen option:** 1.

- One review per deal (`UNIQUE(order_id)`, `UNIQUE(sale_id)`), written only by the deal's owner;
  the write locks the deal's row, so two first reviews from two tabs queue into one row.
- Publication is computed, never stored: an edit or a hide takes effect at once, nothing drifts.
- A changed review that stays bad (1–3) is reopened as unresolved — it extends the spec's
  «good → bad unpublishes and reopens» to every bad edit.
- Partner-API orders (`orders.channel = 'api'`) are not reviewable: a bot bought them.
- The public page sits behind `review_settings.reviews_public` (default off). It shows the count
  and the reviews, **no average and no schema.org `AggregateRating`**: only 4–5★ reviews are
  published, so an average would always read 4+ (owner ruling 2026-10-23).

### Positive consequences

- No new dependency and no new external call (AGENTS §11 untouched); the live prompt reuses the
  nudges `orders` and `sales` already send.
- One new ip_guard bucket, `review`.

### Negative consequences

- Review text and Steam display names become public data once the page is on
  (`docs/security/pii-handling.md`).
- There is no account-erasure flow yet: a user's review text is not deleted on request.
- A card sale's «Выплачено» can be undone for 10 minutes (`sales/admin_undo.py`), but the prompt
  fires at once. A review written in that window stays after an undo: the deal stops being
  reviewable (no new prompt, no edit), the review itself is kept — it is still the seller's word
  about the deal, and the payout is normally marked again. We accept this over delaying every
  card seller's prompt by 10 minutes.

## Validation

`test_reviews_*` (the rule 7 matrix, publication, ownership, concurrency, a PII-free public
payload); the admin's «Плохие» tab and the `csmarket_reviews_bad_open` gauge in use.
