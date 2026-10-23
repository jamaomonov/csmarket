# Reviews: market and buy-back

Approved in conversation with the owner on 2026-10-23.

## Goal

Collect a 1–5 star rating and an optional text after every successful deal — a delivered
order (market) and a paid sale (buy-back) — to help unhappy users quickly and, once there
are enough good reviews, show them on the site. Reviews are hidden from everyone until the
owner switches the public page on.

## Owner rulings

1. **Two categories:** `market` (an order) and `sale` (a buy-back), for our own sorting.
2. **Good = 4–5 stars, bad = 1–3.** A good review is published by itself once the public page
   is on; a bad one is never published. Bad reviews have their own admin tab, so an admin
   contacts the user, helps and marks the review «Разобрано» with a note.
3. **The public page is off** behind an admin switch until enough reviews are collected.
4. **The live prompt shows on any page** of the site, the moment the deal succeeds.
5. **The reminder is a bottom strip, not a modal:** once per visit; «Не сейчас» hides it for
   3 days, × hides it for that deal for good; no prompt 14 days after the deal.
6. **The language is recorded:** the interface locale (`ru` / `uz` / `en`) at submission,
   for sorting by language. The text itself is not language-detected.
7. **When a deal can be reviewed:**
   - order: status `delivered` (the buyer accepted the trade), from `delivered_at`;
   - sale to the balance: status `credited` (the 7-day hold ended and the money is on the
     balance), from `credited_at`;
   - sale to a card: its payout request `paid`, from the request's `paid_at`.
8. **Letters** already exist and stay: `sale_paid` on the balance credit and on «Выплачено»
   (`sales/letters.py`), sent only to a confirmed address.

## Data (`modules/reviews`)

`reviews`:

| Column                                          | Meaning                              |
| ----------------------------------------------- | ------------------------------------ |
| `id` PK                                         |                                      |
| `kind`                                          | `market` / `sale`                    |
| `order_id` / `sale_id`                          | exactly one set; each unique         |
| `user_id`                                       | the author (the deal's owner)        |
| `rating`                                        | 1–5                                  |
| `text`                                          | ≤ 1000 chars, nullable; plain text   |
| `locale`                                        | `ru` / `uz` / `en`                   |
| `hidden`                                        | an admin hid it from the public page |
| `resolved_at` / `resolved_by` / `resolved_note` | a bad review handled by an admin     |
| `created_at` / `updated_at`                     |                                      |

Published = `rating >= 4 AND NOT hidden` (computed, not stored). Editable by its author for
14 days after the deal; an edit that makes it bad unpublishes it and reopens it as unresolved.

`review_prompts` (one row per user and deal): `snoozed_until` («Не сейчас», +3 days),
`dismissed` (×). Server-side so it works across devices.

Settings: `reviews_public` (bool, default off) in the existing admin settings store.

## API

| Route                                               | What                                                              |
| --------------------------------------------------- | ----------------------------------------------------------------- |
| `GET /reviews/pending`                              | the newest deal of the user to review now (or none)               |
| `PUT /reviews/{kind}/{number}`                      | create or edit the review (`Idempotency-Key`, rate-limited)       |
| `POST /reviews/{kind}/{number}/snooze`              | «Не сейчас» (3 days)                                              |
| `POST /reviews/{kind}/{number}/dismiss`             | × (for good)                                                      |
| `GET /reviews` (public)                             | published reviews, paginated; 404-like empty when the page is off |
| `GET /admin/reviews?tab=bad/all/good&kind=&locale=` | the list, keyset-paginated                                        |
| `POST /admin/reviews/{id}/resolve`                  | «Разобрано» + note (audited)                                      |
| `POST /admin/reviews/{id}/hide` / `unhide`          | hide from the public page (audited)                               |
| `PUT /admin/reviews/settings`                       | `reviews_public` (audited)                                        |

`pending` returns at most one deal: reviewable (rule 7), within 14 days, without a review, not
dismissed, not snoozed; newest first. It carries the kind, number, skin name and picture.
The public list returns the Steam display name and avatar, stars, text, the skin name
(market) or «Продажа скинов» (sale), the date and the locale; never a Steam ID, an email or
an amount.

## Storefront

- **Live prompt:** the site-wide socket (`Providers.tsx` → `useOrderSocket`) already gets
  `order.changed` and `sale.updated`. On either, the client asks `GET /reviews/pending`; a deal
  that became reviewable in this visit opens the modal at once on any page.
- **Modal:** the skin picture, «Обмен прошёл! Как вам покупка?» (sale: «Как прошла продажа?»),
  5 stars, the text field. The placeholder follows the stars: 1–3 «Расскажите, что
  случилось?», 4–5 «Пару тёплых слов — это нам очень помогает». «Отправить», «Не сейчас».
  After sending: a short thank-you; a bad review adds «Мы свяжемся с вами».
- **Reminder strip:** on a page load with a pending deal, a bottom strip «Как прошла покупка
  <скин>?» (sale: «Как прошла продажа?») with stars; a star opens the modal with it chosen.
  Once per visit (sessionStorage), «Не сейчас» → snooze, × → dismiss.
- **Account:** a delivered order / paid sale shows «Оставить отзыв» or the stars given (edit
  within 14 days).
- **`/reviews`:** while off, the current «Скоро» page (noindex). When on: average rating and
  count, the published reviews, the visitor's locale first; schema.org `AggregateRating`.
- All copy in ru / uz / en.

## Admin

- **«Отзывы»** in the «Люди» group, a counter of unresolved bad reviews in the menu.
- Tabs «Плохие N» (unresolved first), «Все», «Хорошие»; filters kind and language.
- A row: stars, text, language, the user (link), the order / sale (link), when.
- A bad review: «Разобрано» with a note. Any review: «Скрыть с сайта» / «Показать».
- **Settings:** «Показывать отзывы на сайте» switch with the count of published reviews beside
  it; a confirm when switching on.

## Rules

- Only the deal's owner reviews it; a deal not reviewable (rule 7) or older than 14 days is
  409 `review_not_allowed`.
- Text is stored as typed, rendered as text (no HTML), trimmed, ≤ 1000 chars; never logged.
- Rate limit on `PUT /reviews/…` (ip_guard bucket `review`).
- Metrics: `csmarket_reviews_total{kind, rating}`; a gauge of unresolved bad reviews and an
  alert-free dashboard tile (no Telegram alert — the menu counter is enough).

## Testing

- The rule 7 matrix: delivered / not, credited / not, card paid / not, 14-day edge, an
  existing review, snooze and dismiss.
- Publish logic: 4–5 published, 1–3 never, hidden never, edit good → bad unpublishes.
- Ownership, idempotent replay, the rate limit, text limits.
- Public list off → empty / «Скоро»; on → only published, no PII fields.
- Web: the modal opens on a socket nudge on any page, the placeholder switches with the
  stars, the strip shows once per visit, snooze / dismiss calls; the three locales.
- Admin: tabs, resolve, hide, the switch.
- Coverage: `reviews` joins the 95 % list.

## Docs

ADR-0023 (reviews: one per deal, computed publication, server-side prompts), the module
README, `module-map.md`, `docs/product/flows/review.md` with a sequence diagram,
`docs/api/README.md`, `metrics.md`, `pii-handling.md` (review text and display names on a
public page).
