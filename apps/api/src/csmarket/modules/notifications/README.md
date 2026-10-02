# notifications

Transactional email for csmarket (M4b, ADR-0008). Email only: no SMS, no push, no marketing.

- **What it owns:** the `email_outbox` table, the worker's `emails` queue
  (`sender.drain_emails`), the Resend client, the dev transport, and the dev-only
  `GET /api/v1/dev/emails`.
- **Letters:** `receipt`, `trade_sent`, `refunded` (order letters, one per order and kind) and
  `verify` (the email confirmation). Rendered in the user's locale by `templates` (copy in
  `copy.py`, ru / uz / en; table layout, one button, a plain link under it; no images, no
  external fonts, no tracking). The payload snapshots what a letter shows — the order
  number, the skin, the offer's deadline or the refunded amount — so the worker never reads
  `orders`. Enqueued by `orders.letters` at `mark_paid`, `trades.apply` → `trade_sent` and
  `refund_to_balance`.
- **Enqueue:** `notifications.api.enqueue(db, kind=…, user_id=…, order_id=…, address=…,
payload=…)` inside the event's own transaction — the row and its `NOTIFY emails` land on
  commit or not at all. Flushes, never commits. A replayed event returns `None`.
- **Recipient:** resolved when the letter is sent. Order letters go to the user's email only
  while it is verified; a `verify` letter only while the address it confirms is still the
  user's and unverified. Otherwise the row is `skipped` (never retried).
- **Sending:** the claim counts the attempt and books the next one (1, 5, 15, 60, 180,
  600 min), commits, then sends with no lock or open transaction; the row id is the
  provider's `Idempotency-Key`. A 4xx other than 429 → `failed` at once; six retryable
  failures → `failed`. Metric `csmarket_emails_total{kind,outcome}`; alert `EmailsFailing`
  (`docs/runbooks/email.md`).
- **Transports:** `resend` (prod; prod refuses `dev`) or `dev` — the last 50 letters in Redis
  `notifications:dev:mail` for an hour, filed by user id.
- **Imports:** `users.models` (the recipient). Nothing from `orders` or `payments` at import
  time; they import `notifications.api`.
- **Never logged or stored outside the row:** the address, the Resend key, a verification
  token. Log lines carry the outbox id, the kind and the outcome.
