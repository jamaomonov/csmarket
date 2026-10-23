# reviews

1–5 stars and an optional text after a successful deal (spec `2026-10-23-reviews-design.md`,
ADR-0023, flow `docs/product/flows/review.md`).

**Owns:** tables `reviews` (one per order or sale), `review_prompts` («Не сейчас» / × per deal)
and `review_settings` (row 1: `reviews_public`, the public page's switch) — migration
`0040_reviews`.

- `deals.py` — rule 7: an order is reviewable when `delivered` (not a partner-API order), a sale
  to the balance when `credited`, a sale to a card when its payout request is `paid`; for 14 days
  after that. `pending_for` picks the newest deal to ask about.
- `service.py` — the user's routes: `pending`, `deal_review`, `save_review` (locks the deal's row:
  two first reviews queue into one), `snooze`, `dismiss`.
- `public.py` — `GET /reviews`: 200 with `enabled: false` while the page is off; otherwise the count
  and the published reviews (`rating >= 4 AND NOT hidden`, by live accounts), the visitor's locale
  first. No average (ADR-0023).
- `admin.py`, `admin_routes.py` — tabs `bad` / `all` / `good`, «Разобрано», hide / unhide, the
  switch; every write audited (`reviews.review.resolve` / `hide` / `unhide`,
  `reviews.settings.save`) with kind, number and rating only.
- `api.py` — `bad_open_count`, used by `admin.dashboard_routes` and the scheduler's
  `reviews.bad_open` job (gauge `csmarket_reviews_bad_open`).

**Imports:** `orders.api` (`Order`), `sales.api` (`Sale`, `PayoutRequest`, `SaleItem`),
`skins.api`, `users.api` (`User`), `admin.api` (audit, idempotent replay), `auth.api`
(`current_user`, `guard_ip` bucket `review`).

**Never logged:** the review text, the admin's note, display names.
