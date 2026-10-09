# 0017. The public purchase API and the USD wallet

- **Status**: Accepted
- **Date**: 2026-10-09
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | data

## Context and problem statement

Resellers (YuPay first) want to buy skins from us over an API, in dollars. The storefront ledger
holds soʻm only. Spec: `docs/superpowers/specs/2026-10-09-public-api-design.md`; delivery in
three plans, A (this ADR's part: the USD wallet), B (keys, buying), C (webhooks, ops).

## Decision drivers

- The API's prices are dollars; no rate in the contract.
- One ledger, one `post` invariant; no float, no second money store.
- An admin decides who gets a dollar wallet; no path from dollars back to soʻm.

## Considered options

1. **A currency column on `wallet_accounts`**, separate dollar accounts, balance checked per currency.
2. **A separate USD ledger** (own tables) beside the soʻm one.
3. **Convert per order** from the soʻm balance at purchase time.

## Decision outcome

**Chosen option:** 1, because the invariant, idempotency keys, row locks and history code carry
over unchanged and a transaction can still be atomic across both currencies.

- **Per-currency ledger.** `wallet_accounts.currency` (`UZS` | `USD`); USD is integer milli-USD
  (1000 = $1) in the same `Numeric(14,0)`. `post` requires SUM(D) = SUM(C) per currency.
- **Two house FX accounts.** One `house_fx` cannot hold two currencies under the
  `(owner_type, owner_id, kind)` key, so `house_fx_uzs` (debit-normal) and `house_fx_usd`
  (credit-normal) are the conversion's counter-accounts; new kinds `user_wallet_usd`,
  `house_payments_received_usd`, `house_adjustments_usd`; tx kinds `fx_convert`, `admin_adjust_usd`.
- **Conversion** at the site rate (`fx.api.current_usd_uzs`, CBU × (1 + `fx_uplift_pct`),
  ADR-0011): `usd_units = floor(amount_uzs × 1000 / rate)`; ledger key `fx_convert:` + sha256 of
  `user_id:Idempotency-Key`. Soʻm to dollars only.
- **The switch.** `users.usd_wallet_enabled`, set by an admin (audited `wallet.usd_switch`). Off
  keeps the money; conversion and API purchases stop. Dollars enter by conversion or by an
  admin's audited credit (`wallet.adjust_usd`).
- **Customer API.** `GET /wallet` gains `usd`; `POST /wallet/convert`; `GET /wallet/entries?currency=`.

### Positive consequences

- Dollar reports come from the ledger: `house_fx_uzs` and `house_fx_usd` say what was converted.
- Plan B debits the USD wallet with the existing `purchase` / `refund` kinds, the account deciding.

- Plan B: the partner API reuses the same ledger and the same buy worker; an API order is a paid
  `orders` row (`channel = api`), so refunds, attention and reconciliation need no new states.

### Plan B consequences (rulings R1–R5)

- **R1 — no nullable site columns.** `price_uzs`, `fx_snapshot_id` and `fx_uplift_pct` stay
  NOT NULL: an API order stores `price_uzs = 0`, the newest FX snapshot (any age; none ever
  recorded is 503 `rate_unavailable`), `fx_uplift_pct = 0`; `price_usd` holds the charged price.
- **R2 — who may issue a key.** A successful top-up **or** `usd_wallet_enabled` (an admin-funded
  client such as YuPay may never top up); otherwise 409 `api_key_not_allowed`.
- **R3 — the token is never stored,** so a replayed issue `Idempotency-Key` answers 409
  `key_already_issued` with the `key_id`, not the token.
- **R4 — the feed is stored as JSON text pages** of 1000 items in Redis (no per-page gzip in the
  app); Caddy gzips the response. A strong ETag per page, 304 on `If-None-Match`.
- **R5 — new failure reasons** `trade_hold` and `price_moved` (Skinslink `hold` /
  `hold_and_permissions` map to `trade_hold`); the partner reads a closed list of refund reasons.
- **Orders are scoped to the key's owner.** `client_order_id` is unique per user among API
  orders (`uq_orders_user_client_order_id`, partial `WHERE channel = 'api'`, migration 0028), so
  a reissued key still reads the old orders and cannot reuse an old id; another user's order is 404. Keys are revoked, never deleted (`orders.api_key_id` is RESTRICT).
- **No external call on the public path.** The feed and offers read our own tables and Redis;
  the trade link is checked for form only; the buy happens in the worker.

### Negative consequences

- No dollars back to soʻm: a client who wants out is paid by hand (admin debit).
- A feed refresh lags by up to 60 s, and after a scheduler restart the feed is 503 for ~400 s.
- We carry the FX gap between the converted rate and the day we buy; the uplift covers it.

## Validation

Unit and integration tests pin the per-currency invariant, the conversion floor, replay and
mismatch, and the switch. In production: the first YuPay credit and `house_fx_*` sums
(`docs/runbooks/public-api.md`).

## References

- [ADR-0006](./0006-wallet-payments-topups.md) — the ledger; [ADR-0011](./0011-fx-uplift.md) — the rate.
