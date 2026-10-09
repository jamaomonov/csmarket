# 0018. Admin refund of a Skinslink / LIS-SKINS order, checked with the supplier

- **Status**: Accepted
- **Date**: 2026-10-09
- **Deciders**: @jamaomonov
- **Tags**: backend | payments

## Context and problem statement

An admin could refund only a Waxpeer order (ADR-0007 Y): `admin_refund` asks Waxpeer for the
order's `project_id` before it books. A Skinslink (ADR-0010) or LIS-SKINS (ADR-0012) order that
got stuck — a site order or an API order (ADR-0017) — had no admin refund at all: the money
waited for the reconcile, whatever the supplier said. A refund is the one place we could hand
out both the skin and the money, so it must not trust our own rows alone. The owner ruled on
2026-10-09: refund only after the supplier confirms the purchase did not happen. Plan C Task 5
(`docs/superpowers/plans/2026-10-09-public-api-ops.md`), spec §12 C.

## Decision drivers

- Never refund a purchase that may still reach the buyer, even on a second click.
- No lock and no open transaction across an external call (AGENTS §11); one call, bounded.
- The button and the action never disagree; the detail page makes no supplier call.

## Considered options

1. **Ask the supplier once, then lock and book** — the Waxpeer admin refund's shape.
2. **Trust our rows** (stored supplier status, attention resolved by an operator) — no call.
3. **Force a reconcile run** and let it refund.

## Decision outcome

**Chosen option:** 1. `orders.admin_refund_sources.admin_refund_purchase`, reached through
`admin_actions.admin_refund` by `orders.source`:

1. Unlocked read; `purchase_refund_refusal` refuses early (`already_refunded`;
   `order_not_refundable` unless `buying` / `trade_sent`; `order_needs_attention` while an
   attention that blocks refunds (R3) is unresolved; `order_busy` while a buy holds the lease;
   `order_in_flight` for a purchase row younger than 10 minutes with no supplier id). The read
   transaction is committed (nothing written).
2. One supplier call under `asyncio.timeout(4)`, nothing locked: Skinslink
   `GET /merchant/purchase/status` by `merchant_tx_id`, LIS-SKINS `GET /market/info` by
   `custom_id` (`info_answer`, which also counts the answer's entries, unreadable ones
   included). Clients: `skinslink.request_status_client` (4 s) and
   `lisskins.request_info_client` (`lisskins_check_timeout_seconds`, 4 s), FastAPI dependencies.
3. Verdict: Skinslink `failed` / `canceled` → refundable; LIS-SKINS skin `return` (not a
   `rollback_…` reason) → refundable; not found → refundable only with no market purchase id
   on record **and** no lost buy answer (`buy_unconfirmed_at` set → `order_in_flight`: the
   source may not show a purchase whose answer we lost a minute ago — a silence is never
   refunded), the row old and idle (step 1 checked). The answer must be about our purchase:
   a Skinslink report under another `merchant_tx_id` or purchase id, a LIS-SKINS answer that
   has entries but none with our `custom_id`, an unreadable entry, or another purchase id →
   `order_in_flight`. Anything else (`active`, `hold`,
   `completed`, `reverted`, `accepted`, `wait_accept`, `processing`, `wait_unlock`,
   `wait_withdraw`, a rollback return) → `order_in_flight`. Lookup error or timeout → 409
   `source_unavailable`.
4. Lock order → purchase (ruling K), check again; a purchase id or a lost buy answer recorded
   since the read → `order_in_flight` (the answer no longer covers the row). Turn `buy_pending` off and book
   `refund_to_balance` (reason `admin`, actor `admin:<id>`): a `buying` order becomes `failed`,
   a `trade_sent` one `returned` (the FSM has no `trade_sent → failed`). An API order's money
   goes back to its USD wallet; the route audits `orders.refund` and commits as before.

`reverted` (Skinslink) and a rollback return (LIS-SKINS) mean the skin was accepted and then
taken back — it may be spent; they stay with the existing attention paths.

### Positive consequences

- A stuck Skinslink / LIS-SKINS order can be settled by an admin, safely.
- Same guarantees and shape as the Waxpeer refund; the detail's `can_refund` uses the same
  refusal function without the call, and also hides the button while the stored purchase
  status is plainly live (Skinslink `active` / `hold` / `completed`; LIS-SKINS `accepted`,
  `wait_accept`, `wait_unlock`, `wait_withdraw`).

### Negative consequences

- A new external call on an admin request path (AGENTS §11, the eighth carve-out); the route
  was already in the `ApiHighLatency` / `ApiWaxpeerLatency` handler regexes.
- Our stored status lags the source, so the button may still show for a purchase the source
  already reports as live; the answer refuses it (`order_in_flight`) — the source decides.

## Validation

`apps/api/tests/integration/test_admin_refund_sources.py`: each supplier status, refused twice
for live ones with nothing booked (Review Focus 2), not-found by age and by purchase id, timeout
and errors → `source_unavailable`, a fake client that fails if a transaction is open during
the call, the race where a purchase id appears during the lookup, USD and soʻm refunds, the
route's audit and replay.

## Alternatives considered (detail)

### Option 2

No call, no latency — but our stored status lags the supplier (webhooks and polls), and an
operator's check is exactly what the owner did not want to rely on.

### Option 3

The reconcile already refunds `failed` / `canceled` / `return` — the stuck cases are the ones
it does not settle (a silence, an attention); forcing it changes nothing for them.

## References

- [ADR-0007](./0007-orders-buying-trades.md) (the Waxpeer admin refund, ruling Y)
- [ADR-0010](./0010-skinslink-buy-source.md), [ADR-0012](./0012-lisskins-buy-source.md),
  [ADR-0017](./0017-public-api-and-usd-wallet.md)
