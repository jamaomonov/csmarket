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

### Negative consequences

- No dollars back to soʻm: a client who wants out is paid by hand (admin debit).
- We carry the FX gap between the converted rate and the day we buy; the uplift covers it.

## Validation

Unit and integration tests pin the per-currency invariant, the conversion floor, replay and
mismatch, and the switch. In production: the first YuPay credit and `house_fx_*` sums
(`docs/runbooks/public-api.md`).

## References

- [ADR-0006](./0006-wallet-payments-topups.md) — the ledger; [ADR-0011](./0011-fx-uplift.md) — the rate.
