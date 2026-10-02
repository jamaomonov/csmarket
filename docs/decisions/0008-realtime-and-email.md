# 0008. Live order updates, transactional email, the pricing editor and the dashboard (M4b)

- **Status**: Accepted
- **Date**: 2026-10-02
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data | security | observability

## Context and problem statement

M4a (ADR-0007) sold skins end to end with a polling order page; its ruling R15 left four
things for M4b: a live order page, email, the admin pricing editor and the dashboard. The
owner decided while planning (2026-10-01/02):

- **D1.** Order letters go **only to a verified address**; a buyer confirms it by a link, and
  the confirmation letter is the only mail an unverified address gets.
- **D2.** The dashboard shows **today / 7 / 30 days**, cut by Tashkent days (UTC+5).
- **D3.** An order's trade-link **token is erased 30 days after the order ends**, keeping the
  Steam account and the masked form.
- **D4.** A rollback after delivery is never refunded by the app (ADR-0007, unchanged).
- **D5.** **Resend** is the email provider.

Plan: `docs/superpowers/plans/2026-10-02-m4b-live-email-pricing.md` (rulings R1–R13).

## Decision drivers

- A nudge must never arrive before the data it announces.
- A socket must never show another buyer's order; a dead token must end it.
- One event, one letter — whatever replays, re-runs and retries — and none to an unverified
  or changed address. A letter never touches money or an order.
- A failed pricing save leaves the old prices everywhere; a preview writes nothing.
- No new dependency; nothing secret in a URL; no PII in logs.

## Decision

### Live order updates (R1–R4)

- **Postgres `LISTEN`, not Redis pub/sub.** `realtime.api.nudge` runs
  `pg_notify('order_events', '<user_id>:<number>')` inside the status writer's transaction,
  so the nudge is delivered **only on commit** and a client re-reading on it always sees the
  new state. Each API process keeps one asyncpg `LISTEN` connection (reconnecting with
  backoff) and an in-process registry of sockets by user.
- **First-message auth.** `WS /api/v1/realtime/orders`, then `{"type":"auth","token"}` within
  5 s; close **4401** on a bad, revoked or expired token and at the token's expiry, **4429**
  past the `ws-connect` bucket (60/min per IP).
- **Nudges, not payloads:** `{"type":"order.changed","number"}` and a ping every 25 s. The
  storefront re-reads the order, the list, the balance and its entries; polling stays the
  reconciler.
- **Sites:** paid, claimed, trade sent / delivered / rolled back, refunded, expired.

### Email (R5–R7)

- **An outbox in Postgres** (`email_outbox`, migration 0015) written in the event's
  transaction with `NOTIFY emails`; an order letter is unique per `(order_id, kind)`.
  Kinds: `receipt`, `trade_sent` (none when an order jumps straight to `delivered`),
  `refunded`, `verify`. The payload snapshots what the letter shows (number, skin, deadline,
  amount), so the sender never reads orders.
- **The worker's `emails` queue** (one drainer) claims due rows `FOR UPDATE SKIP LOCKED`,
  counts the attempt and books the next one (1, 5, 15, 60, 180, 600 min) in the claim's own
  transaction, then sends **with no lock and no open transaction**, the row id as Resend's
  `Idempotency-Key`. A crash leaves the row due at the booked time: same key, one letter. A
  4xx other than 429 fails the row at once; six retryable failures fail it;
  `csmarket_emails_total{kind,outcome}` and the alert `EmailsFailing`.
- **The recipient is resolved at send time:** an order letter needs the user's email
  verified; a `verify` letter needs its snapshotted address to still be the user's,
  unverified — else `skipped`. Letters never carry a trade link, a Steam ID or the balance.
- **Dev transport:** `email_transport=dev` keeps the last 50 letters in Redis
  (`notifications:dev:mail`, 1 h), filed by user id (no address), read through the dev-only
  `GET /api/v1/dev/emails`. Prod resolves an unset transport to `resend` and refuses `dev`;
  a missing `CSMARKET_RESEND_API_KEY` is reported at start-up.
- **Confirmation:** a stateless token — `user_id | email | expiry` sealed with SecretBox under
  the `csmarket:email-verify:v1` purpose key (`core.crypto`), base64url, 24 h. It travels in
  a URL, so it is opaque (neither the address nor the account readable) as well as
  tamper-evident. `PATCH /me` with a new address queues a letter; `POST
/me/email/verification` re-sends after a 60 s cooldown; `POST /email/confirm` is anonymous
  and idempotent and confirms only while the account's email is still the token's.

### Pricing editor (R8)

`GET/PUT /admin/skins/pricing`, `POST /admin/skins/pricing/preview`, `PUT
/admin/skins/items/{slug}/pricing`. A save takes `lock_pricing`, saves, reprices every
active item, audits, commits — and only then publishes the rules to Redis and bumps the
catalogue version. The preview reads Postgres only (`settings.read_rules`) and writes
nothing. A per-item margin override or pinned price reprices that item alone.

### Dashboard (R9, R10)

`GET /admin/dashboard?days=1|7|30`: sales (paid in the window, not refunded; cost =
`COALESCE(bought_units / 1000, cost_usd)`; margin and its percent of revenue), refunds by
`refunded_at`, orders in flight and open attentions now, one row per Tashkent day (cut in
Postgres with `AT TIME ZONE 'Asia/Tashkent'`), four queries whatever the window
(migration 0016 indexes `paid_at` / `refunded_at`). The Waxpeer balance is the
`orders.health` job's last good read, cached in Redis for an hour — no new Waxpeer call on
a request.

### Erase (R11, D3)

The nightly `orders.erase_trade_links` job (22:00 UTC) masks an ended order's trade link
after 30 days (`partner` kept; `trade_link_erased_at`, migration 0017) and drops a `verify`
row's address a week after it was queued.

### Execution refinements (from the ledger)

- The email claim books the next attempt before sending, instead of holding the row lock
  across the Resend call (AGENTS §11).
- The confirmation token is SecretBox-sealed, not a readable HMAC (no PII in a URL).
- The confirm page reads the token from the address bar and strips it with
  `history.replaceState` (not a server prop serialised into the page).
- The socket client resets its backoff and its one-refresh allowance when the server first
  speaks, not on open (the server accepts every socket before it reads the auth frame).
- A close or ping to a client already gone ends the socket quietly (found in e2e).
- The one-letter-a-minute cooldown also holds on `PATCH /me` (a changed address within the
  minute is saved, not mailed), and an email edit is charged to the `email-verify` bucket —
  otherwise alternating two addresses would mail a stranger in a loop (final review).

## Consequences

- One more worker queue; one more `LISTEN` connection per API process (a second API replica
  would LISTEN too and serve its own sockets).
- Resend, as a processor, receives the recipient address, the subject and the body.
- A lost or failed letter never blocks money or an order; the buyer sees everything on the
  order page.
- Dependencies added: **none** (httpx, asyncpg, PyNaCl and the existing UI stack).

## Considered alternatives

### Redis pub/sub per socket

YuPay published to Redis before commit: a fast client could re-read the old state. Postgres
`NOTIFY` is transactional and already powers the worker queues. Rejected (R1).

### The token in the WebSocket URL

URLs are logged by browsers, Cloudflare and Caddy. A first frame keeps the token out of
every log and needs no new JWT kind. Rejected (R2).

### Sending email inline after commit (as YuPay)

An after-commit send is lost on a crash between commit and send, and retries need their own
state. The outbox gives atomic enqueue, retries and idempotency for one table. Rejected (R5).

### An email SDK

Resend is one `POST /emails`; httpx and respx cover it with no new dependency. Rejected.

## References

- Plan `docs/superpowers/plans/2026-10-02-m4b-live-email-pricing.md`; ADR-0007 (R15)
- Runbooks: [`email.md`](../runbooks/email.md), [`pricing.md`](../runbooks/pricing.md),
  [`orders.md`](../runbooks/orders.md)
- Diagrams: `docs/architecture/sequence-diagrams/{order-live,email-outbox}.mmd`; flow
  [`email-confirm.md`](../product/flows/email-confirm.md)
- Module READMEs: `apps/api/src/csmarket/modules/{realtime,notifications,orders,skins,users,admin}/README.md`
- Alerts: `infra/prometheus/alerts/notifications.yml`; metrics: `docs/architecture/metrics.md`
