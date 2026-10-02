# 0008. Live order updates and transactional email (M4b)

- **Status**: Proposed (draft — M4b Task 14 completes it)
- **Date**: 2026-10-02
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data | security | observability

## Context and problem statement

M4a's order page polls. M4b (plan `docs/superpowers/plans/2026-10-02-m4b-live-email-pricing.md`)
makes it live and adds the three order letters — receipt, trade sent, refunded — plus the
email confirmation they depend on. The owner decided (2026-10-01/02): Resend is the provider
(D5), and order letters go **only to a verified address** (D1).

## Decision

### Live order updates (R1–R4)

- **R1 — Fan-out through Postgres `LISTEN`.** Every status writer runs in a transaction its
  caller commits; `realtime.api.nudge` issues `pg_notify('order_events', '<user_id>:<number>')`
  in it, so the nudge is delivered **only on commit** and a client re-reading on it sees the
  new state. The API process keeps one asyncpg `LISTEN` connection (reconnecting with
  backoff) and an in-process registry of sockets by user.
- **R2 — Auth by the first message**, `{"type":"auth","token":…}` within 5 s; close 4401 on a
  bad token and at the token's expiry, 4429 past the `ws-connect` bucket. Nothing secret in
  a URL.
- **R3 — Nudges, not payloads:** `{"type":"order.changed","number"}` and a ping every 25 s.
  Polling stays the reconciler.
- **R4 — Nudge sites:** paid, claimed, trade sent / delivered / rolled back, refunded,
  expired.

### Email (R5–R7)

- **R5 — An outbox in Postgres** (`email_outbox`), written in the transaction of the event it
  reports with `NOTIFY emails`; an order letter is unique per order and kind. The worker's
  `emails` queue claims due rows (`FOR UPDATE SKIP LOCKED`), counts the attempt and books the
  next one (1, 5, 15, 60, 180, 600 min) in the claim's own transaction, then sends **without a
  lock or an open transaction** with the row id as Resend's `Idempotency-Key`. A crash leaves
  the row due again at the booked time — the same key, one letter. The recipient is resolved
  at send time: an order letter needs the user's email verified; a `verify` letter needs its
  snapshotted address to still be the user's, unverified — otherwise `skipped`. A 4xx other
  than 429 fails the row at once; six retryable failures fail it; `EmailsFailing` alerts. A
  letter never touches money or order state.
- **R6 — Dev transport:** `email_transport = dev` keeps the last 50 letters in Redis
  (`notifications:dev:mail`, 1 h), read by their owner through the dev-only
  `GET /api/v1/dev/emails`. Prod resolves an unset transport to `resend` and refuses `dev`;
  a missing `CSMARKET_RESEND_API_KEY` is reported at start-up.
- **R7 — Email confirmation** by a stateless HMAC link valid 24 h (Task 5).

## Consequences

- One more queue in the worker, one more LISTEN connection per API process.
- Resend sees the recipient address and the letter; nothing else about the buyer.
- Letters carry no trade link, Steam ID or balance.
