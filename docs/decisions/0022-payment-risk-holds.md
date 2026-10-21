# 0022. Payment risk limits: fail-closed holds on settle

- **Status**: Accepted
- **Date**: 2026-10-21
- **Deciders**: owner
- **Tags**: payments | security

## Context and problem statement

A kassa is frozen when carded cards run through it (YuPay `4f4f13b4` hit exactly this). Money
that comes in through a kassa above a set amount must not turn into a balance or a bought skin
on its own, and splitting a payment into small ones must not get round the limit. Spec:
`2026-10-21-payment-risk-limits-design.md`.

## Decision drivers

- Every kassa (Click, Payme, Uzum, P2P) lands its money in one place, `payments.hooks.settle`.
- The kassa has already taken the money; refusing it is not possible, deciding what we do with it is.
- Two settles of one user through two kassas at once must not both slip under the limit.

## Considered options

1. **Refuse before paying** — block a payment above the limit when it is created.
2. **Hold on settle, fail-open** — hold over the limit, let through when the check fails.
3. **Hold on settle, fail-closed** — hold over the limit and when the check fails.

## Decision outcome

**Chosen option:** 3. `settle` calls `risk.verdict` under `pg_advisory_xact_lock` per user; the
reads run in a savepoint, so any exception holds the payment with reason `check_failed`
(logged as `payments.risk.check_failed`, no PII). Equality passes (sum <= limit). A trusted
user bypasses both limits.

- A hold is a `payment_holds` row plus status `held` on the top-up or order (`TOPUP_STATUSES`,
  `ORDER_STATUSES`); `rejected` is the top-up's end after a return. The kassa is answered as for
  a success, nothing is credited, no `NOTIFY orders`.
- Limits: `kassa_review_limits` per provider (seed 2 000 000 soʻm / 24 h, on) and
  `user_risk_policies` per user (trusted, `kassa_blocked`, own limit). `kassa_blocked` refuses
  starting a kassa payment with 403 `kassa_payment_blocked` (`risk.block.ensure_kassa_allowed`).
- «Пропустить» goes through the normal paths (`credit_topup`, `mark_paid`). «Вернул на карту»
  records that the admin returned the money in the kassa's cabinet (card transfer for P2P): the
  attempt goes `refunded`, a top-up `rejected`, an order `cancelled`; never to the balance.
- A kassa reversing a held payment itself (Payme `CancelTransaction`, Uzum reverse) closes
  the hold `reversed_by_kassa`, top-up `reversed` with no debit, order `cancelled`. This
  is the one exception to R7 (an order payment is never reversed): a held order bought nothing.
  Click sends no reversal: after a refund in its cabinet the admin presses «Вернул на карту».
- `credit_received_transfer` (an admin crediting an unmatched P2P transfer) passes
  `check_risk=False`: it is the admin's own decision.

### Positive consequences

- No kassa path can bypass the check; one lock orders concurrent settles of a user.
- An unavailable check cannot let money through.

### Negative consequences

- A held order's lot may sell meanwhile; release then ends in the usual buy failure refund to
  the balance (the admin approved the money, so that is right).
- Limits count the attempt's base amount, not the kassa fee.
- IP and device are not used (one mobile address in Uzbekistan hides hundreds of people).
- A database fault holds payments until an admin looks (alert `PaymentHeldForReview`).

## Validation

Metric `csmarket_payment_holds_open{reason}` and the alert; integration tests per kassa; the
`risk` module is on the 95 % coverage list.

## Alternatives considered (detail)

### Refuse before paying

Rejected by the owner: the buyer would be turned away at the kassa for an honest large top-up;
a hold keeps the money and the choice.

### Fail-open

YuPay's choice, because its check calls out. Ours is one query in our own database inside the
settle transaction; failing open would let a fault open the gate. Rejected.

## References

- Runbook: [`payment-held-for-review.md`](../runbooks/payment-held-for-review.md)
- Flow: `docs/product/flows/payment-hold.md`; diagram `docs/architecture/sequence-diagrams/payment-hold.mmd`
- [ADR-0006](./0006-wallet-payments-topups.md) for the ledger and top-ups; [ADR-0021](./0021-p2p-topup-shared-bot-relay.md) for P2P
