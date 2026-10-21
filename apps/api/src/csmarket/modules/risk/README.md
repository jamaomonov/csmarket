# risk

Limits on money that comes in through kassas (spec `2026-10-21-payment-risk-limits-design.md`,
ADR-0022). Over a limit means held for an admin, never refused. Runbook:
`docs/runbooks/payment-held-for-review.md`.

**Owns:** tables `kassa_review_limits` (per provider; seeded Payme, Click, Uzum, P2P at
2 000 000 soʻm / 24 h, on), `user_risk_policies` (trusted, `kassa_blocked`, own limit, note)
and `payment_holds` (migration `0039_payment_risk`).

- `rule.py` — `verdict(db, payment)`: takes `pg_advisory_xact_lock` on the user, reads the
  sums in a savepoint, passes a trusted user, then judges the kassa limit and the user limit
  (equality passes). Any exception holds with `check_failed` (fail-closed).
- `block.py` — `ensure_kassa_allowed(db, user_id)`: 403 `kassa_payment_blocked` for a user with
  `kassa_blocked`; kept apart from `policy.py` because of an import cycle.
- `policy.py`, `limits.py` — reading and saving a user's policy and the kassa limits.
- `admin_routes.py` — `GET` / `PUT /admin/payments/review-limits` (`If-Match`),
  `GET` / `PUT /admin/users/{id}/risk`; every write takes `Idempotency-Key` and is audited
  (`payments.review_limits.update`, `users.risk.update`).

**Interface (`api.py`):** `verdict`, `ensure_kassa_allowed`, the policy and limit readers.

**Who calls it:** `payments.hooks.settle` (the verdict; `check_risk=False` only for
`credit_received_transfer`), the places that start a kassa payment (`POST /wallet/topups`,
paying an order through a kassa, a new P2P request) call `ensure_kassa_allowed`.

**Not here:** the hold rows' lifecycle and the admin decisions live in
`payments/holds.py`, `holds_admin.py` and `holds_routes.py` (`/admin/payments/holds`).
Money is `Decimal` whole soʻm; logs carry numbers, providers and amounts only.
