# Payment risk limits: per kassa and per user

Approved in conversation with the owner on 2026-10-21. Modelled on YuPay's per-kassa review
limit (YuPay `4f4f13b4`: `payment_review_limits`, `orders/provider_limit.py`, runbook
`order-held-for-review.md` «Per-kassa spend limit») and its account policy
(`orders/account_policy.py`), brought over by the YuPay session's brief and cut to what the
owner chose here.

## Goal

A kassa is frozen when carded cards run through it. Money that comes in through a kassa above
a set amount must not turn into a balance or a bought skin on its own: it waits for an admin.
Splitting a payment into smaller ones must not get round the limit. The owner tunes every
limit in the admin, per kassa and per user.

## Owner rulings

1. **Over the limit = held, not refused.** The kassa payment goes through; a top-up is not
   credited and an order's skin is not bought until an admin decides.
2. **Kassa limits start on:** Payme, Click, Uzum and P2P, each **2 000 000 soʻm per 24 h**,
   seeded by the migration, editable in the admin.
3. **The user limit counts money in through kassas over a window** (top-ups plus kassa-paid
   orders, every kassa together), not purchases. It exists only for a user the admin sets it
   on; there is no default limit for everyone.
4. **A trusted user bypasses both limits.**
5. **A failed check holds** (fail-closed), unlike YuPay's fail-open: the check is one query in
   our own database inside the settle transaction.
6. **Not now:** new-account rules, a night multiplier, a country veto (YuPay ADR-0062/0063).
7. **One buyer = one account.** No IP, no device (behind one mobile-carrier address in
   Uzbekistan sit hundreds of people).

## The rule

The one place every kassa's money lands is `payments.hooks.settle` (Click, Payme, Uzum
callbacks and the P2P intake alike). Before it credits a top-up or marks an order paid, it
runs `risk.verdict(db, payment)`:

1. Take `pg_advisory_xact_lock` on the user (two settles of one user, through two kassas at
   once, are checked one after the other; the lock ends with the transaction).
2. The user's policy has `trusted` → **pass**.
3. **Kassa limit** (the row for `payment.provider`, if `enabled`): the sum of the user's
   payments through this provider whose money stayed with us — status `succeeded` and
   `succeeded_at` inside the last `window_hours` (held ones included: their attempt is
   `succeeded`) — plus this payment. Above `max_amount_uzs` → **hold `kassa_limit`**.
4. **User limit** (if the policy sets `max_amount_uzs`): the same sum over every provider in
   the policy's `window_hours`. Above → **hold `user_limit`**.
5. Otherwise **pass**.
6. Any exception from steps 2–4 → log `payments.risk.check_failed` (no PII) and **hold
   `check_failed`**.

Refunded attempts (`refunded`) do not count; money returned by an admin («Вернул на карту»)
does not count either, because its attempt goes `refunded`. `usd_wallet` and `wallet`
payments never reach `settle` and are not limited; an admin's «Зачислить пользователю» for an
unmatched P2P transfer (`credit_received_transfer`) is an admin's own decision and is not
checked.

Equality passes: the limit is the largest sum allowed without a check.

## Hold

A hold is a `payment_holds` row and a status on the owner:

| Owner  | Status on hold | Attempt     | What does not happen                         |
| ------ | -------------- | ----------- | -------------------------------------------- |
| Top-up | `held`         | `succeeded` | `wallet.credit_topup`                        |
| Order  | `held`         | `succeeded` | `mark_paid` (no `NOTIFY orders`, no receipt) |

`held` is a new value in `TOPUP_STATUSES` and `ORDER_STATUSES`. It is not `pending` (no second
payment, no expiry sweep) and not `IN_FLIGHT` (no buy). The kassa is answered as for a
successful payment — the money is ours to keep or return.

### Admin decisions

- **«Пропустить» (`release`):** a top-up goes `succeeded` and is credited (`credit_topup`,
  keyed by the top-up as today); an order goes `paid` through `mark_paid` and the worker buys
  at once. If the lot sold meanwhile, the usual buy failure refunds to the balance — the admin
  approved the money, so that is right.
- **«Вернул на карту» (`returned`):** the admin has returned the money in the kassa's cabinet
  (or by card transfer for P2P) and records it. The attempt goes `refunded`; a top-up goes
  `rejected` (new status) with nothing credited; an order goes `cancelled`. Nothing reaches
  the balance: a carder must not get spendable money.
- **The kassa cancels a held payment itself** (Payme `CancelTransaction` after perform, an
  Uzum reverse; Click sends none, so after a refund in its cabinet the admin presses «Вернул
  на карту»): the attempt goes `refunded`, the hold closes as `reversed_by_kassa`, a
  top-up goes `reversed` with no debit (it was never credited), an order goes `cancelled`.
  Today an order payment is never reversed (R7) because the skin is already bought; a held
  order bought nothing, so the reversal is allowed for it alone.

Both admin actions take `Idempotency-Key`, lock the hold, refuse a decided one
(409 `hold_decided`), and write the audit (`payments.hold.release`,
`payments.hold.returned`) with the number, kassa and amount.

### Buyer

- Top-up page and order page: «Оплата получена, проверяем платёж.» No time promise, no reason,
  no limit, no kassa internals (copy rules §12). ru / uz / en.
- After «Вернул на карту»: «Платёж отменён, деньги возвращены на карту.»
- An order on hold shows no trade countdown.

### Alert

A gauge `csmarket_payment_holds_open` (no labels about a person; label `reason`), refreshed
at scrape. Alert `PaymentHeldForReview`: `> 0` for 1 m → Telegram, with a runbook link
(`docs/runbooks/payment-held-for-review.md`). The runbook says how to look at the user, how to
release, how to return in each kassa's cabinet.

## User policy

`user_risk_policies` (one row per user, absent = no policy):

| Column           | Meaning                                                |
| ---------------- | ------------------------------------------------------ |
| `user_id` PK     |                                                        |
| `trusted`        | bypasses both limits                                   |
| `kassa_blocked`  | the user cannot start a kassa payment at all           |
| `max_amount_uzs` | the user limit; `NULL` = none                          |
| `window_hours`   | 1–720, default 24                                      |
| `note`           | the admin's reason, free text (not shown to the buyer) |
| `updated_by/at`  |                                                        |

`kassa_blocked` is checked where a kassa payment is created (`POST /wallet/topups`, paying an
order through a kassa, a new P2P request): 403 `kassa_payment_blocked`, «Оплата картой
недоступна для вашего аккаунта. Напишите в поддержку.» Balance payments stay allowed. A
payment already in a kassa when the block is set settles as usual and goes through the rule.

## Kassa limits

`kassa_review_limits`: `provider` PK (`payme`, `click`, `uzum`, `p2p`), `enabled`,
`max_amount_uzs` (≥ 1), `window_hours` (1–720), `updated_by/at`. Seeded on, 2 000 000 / 24.
A provider with no row is not limited (`mock` in dev).

## Admin

- **«Настройки оплаты» → «Лимит без проверки»:** one line per kassa — the switch, the sum,
  the window; saved with `If-Match` against a stale tab like the fees, the changed fields in
  the audit (`payments.review_limits.update`).
- **«На проверке»** (new page, a counter in the menu): open holds, newest first — number,
  kind (top-up / order), kassa, amount, reason, the window sum and the limit at hold time, the
  user (link to the card); buttons «Пропустить» and «Вернул на карту» with a confirm. A
  «Решённые» tab lists the last decisions with who and when.
- **User card → «Риск»:** «Доверенный», «Запретить оплату кассой», the limit (sum, window),
  the note; the user's money in through kassas over the last 24 h and 7 d for context.
  Audited (`users.risk.update`).

## API

| Route                                          | What                                    |
| ---------------------------------------------- | --------------------------------------- |
| `GET /admin/payments/review-limits`            | the kassa limits and their version      |
| `PUT /admin/payments/review-limits`            | save all of them (`If-Match`, idem key) |
| `GET /admin/payments/holds?state=open/decided` | the list, keyset-paginated              |
| `POST /admin/payments/holds/{id}/release`      | «Пропустить»                            |
| `POST /admin/payments/holds/{id}/returned`     | «Вернул на карту»                       |
| `GET /admin/users/{id}/risk`                   | the policy and the money-in sums        |
| `PUT /admin/users/{id}/risk`                   | save it (idem key)                      |

Storefront and public API: the `held` and `rejected` statuses appear in the top-up and order
views. The public API never meets them (its orders are paid from the USD wallet), so its
contract does not change.

## Data

- Migration `0039_payment_risk`: the three tables, the new statuses in the check constraints,
  the seed, and an index `payments (user_id, provider, succeeded_at) WHERE status =
'succeeded'` for the window sum.
- `payment_holds`: `id`, `payment_id` (unique), `user_id`, `provider`, `amount_uzs`, `kind`
  (`topup` / `order`), `reason` (`kassa_limit` / `user_limit` / `check_failed`),
  `window_sum_uzs` and `limit_uzs` (nullable for `check_failed`), `created_at`, `decision`
  (`released` / `returned` / `reversed_by_kassa`, nullable), `decided_by`, `decided_at`.

## Where the code goes

A new module `modules/risk` (`api.py`, `models.py`, `rule.py`, `holds.py`, `policy.py`,
`admin_routes.py`, `schemas.py`, `README.md`): it owns the three tables and the verdict.
`payments.hooks.settle` calls `risk.api.verdict` and, on a hold, writes the owner's status;
`risk.holds.release` calls back into `payments` / `wallet` / `orders` through their `api.py`.
Analytics count an order when it is paid, so a held order counts only after release.

## Testing

- The rule: under, equal, over; splitting into small payments over the window; a payment just
  outside the window; held ones counted; returned ones not; trusted bypass; user limit across
  two kassas; an exception → `check_failed`.
- Concurrency: two settles of one user at once through two kassas, sum over the limit — one
  passes, one is held.
- Each kassa end to end (Click, Payme, Uzum, P2P intake): over the limit → held, the kassa
  answered success, nothing credited, no `NOTIFY orders`.
- Release and return for a top-up and an order, the idempotent replay, 409 on a decided hold;
  the kassa reversing a held top-up and a held order.
- `kassa_blocked` refuses each way of starting a kassa payment and allows the balance.
- Coverage: `risk` joins the 95 % list.

## Docs

ADR-0022 (fail-closed holds on settle, the new statuses, R7's exception), the module README,
`module-map.md`, a sequence diagram `payment-hold.mmd`, the runbook, `docs/api/README.md`,
`docs/product/flows/` for the buyer's «Проверяем платёж», `metrics.md`.
