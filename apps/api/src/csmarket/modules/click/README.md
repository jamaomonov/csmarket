# click

Click's Shop API for balance top-ups (spec §3.2, §13; M3 Task 5), ported by allow-list
(ADR-0002). Click does not deliver a webhook: **we are Click's Shop API server**. Click calls
`/prepare` then `/complete` as the customer pays in Click Up or on `my.click.uz`, and we own
the transaction state machine. Every money move goes through the `payments` hooks; this
module never touches `wallet`.

**Owns:** table `click_transactions` (migration `0008_click_transactions`): `id`,
`merchant_prepare_id` (`BIGINT IDENTITY`, unique — the integer Click needs back),
`click_trans_id`, `service_id` (unique together: `uq_click_transactions_trans_service`),
`payment_id` (the attempt, `ON DELETE RESTRICT`), `account` (the top-up number Click sent),
`amount numeric(14,0)` soʻm, `status` `PREPARED` | `CONFIRMED` | `CANCELLED`,
`click_paydoc_id`, `prepare_time`, `complete_time`, `cancel_time`, `created_at`,
`updated_at`. Indexes on `payment_id`, `account`, and `prepare_time WHERE status = 'PREPARED'`
(the timeout sweep's scan).

**Interface (`api.py`):** `ClickTransaction`, `CLICK_STATUSES`, `cancel_stale`,
`PREPARE_TIMEOUT`, `PROVIDER`. The gateway (`payments/gateways/click.py`, provider `click`)
builds the pay link and needs nothing from this module.

## Endpoints

```text
POST /api/v1/payments/click/prepare    action=0
POST /api/v1/payments/click/complete   action=1
```

- **Transport:** `application/x-www-form-urlencoded`, parsed with the standard library
  (≤ 8 KiB, ≤ 32 fields); anything else is `-8`. Response JSON.
- **Always HTTP 200**, `{"error": <int>, "error_note": <str>, ...echo}`; the echo carries
  `click_trans_id` / `merchant_trans_id` exactly as sent. A commit failure is `-7`; a
  non-POST is `-8`, never a 405.
- **Auth:** `sign_string`, checked before any business logic, constant-time and
  case-insensitive, over the **raw** wire strings (`"1000.00"` ≠ `"1000"`):
  - prepare: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount + action + sign_time)`
  - complete: the same with `merchant_prepare_id` right after `merchant_trans_id`.
- **One service:** only `CSMARKET_CLICK_SERVICE_ID` has a secret; any other `service_id`,
  or a blank secret, is `-1`.
- Exempt from slowapi (`bootstrap._exempt_self_authenticating_routes`).
- Logs: `click.callback method= error= number= amount=` — never the sign string, the secret
  or a user id.

## Flow

1. The customer opens a top-up with provider `click`; `intent_url` is
   `{click_pay_url}?service_id=&merchant_id=&amount=<soʻm>&transaction_param=<number>&return_url=<our top-up page>`.
2. **prepare** — resolve the top-up (`-5` unknown, `-4` paid, `-9` expired or reversed),
   `amount` must equal it in soʻm (`-2`; tiyin is wrong), then `ensure_attempt(click)` →
   `mark_pending` and a `PREPARED` row. A replay of `(click_trans_id, service_id)` answers
   the same `merchant_prepare_id`, also after losing a concurrent insert (SAVEPOINT).
3. **complete** — the row by `merchant_prepare_id` (`-6` unknown or mismatched
   identifiers), `-4` already `CONFIRMED`, `-9` `CANCELLED`, `-2` amount; then `settle` →
   the top-up is credited once, the row `CONFIRMED`.
4. A **negative inbound `error`** on either call means Click aborted: the `PREPARED` row is
   cancelled and we answer `-9`. A `CONFIRMED` row is never touched (Click has no
   merchant-initiated reversal; refunds happen on Click's side).
5. **Timeout:** the scheduler job `click.timeout` (every 5 min, first run after 160 s)
   cancels `PREPARED` rows older than 30 minutes. The top-up expiry sweep then closes the
   top-up.

### One credit per top-up

- prepare on a paid top-up → `-4`.
- complete when the top-up was paid meanwhile — through another kassa, or through a sibling
  Click row sharing the same attempt (a retried checkout reuses the live attempt) → `-4`,
  and the row is **committed** as `CANCELLED` (`ClickError.persist`), so Click cancels this
  second charge.
- Cancelling a row cancels its attempt only when no other `PREPARED` row still holds it,
  and `cancel_pending` never pulls a settled attempt back.

## Lock order

Global: **top-up → Click row → payment → user wallet.**

| Handler        | Sequence                                                                                                                                                                                                               |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| prepare        | `resolve(number, lock=True)` (top-up) → Click row by `(click_trans_id, service_id)` `FOR UPDATE` (replay) or insert → `mark_pending` (top-up again, then payment)                                                      |
| complete       | read the row by `merchant_prepare_id` **without** a lock → `resolve(row.account, lock=True)` → row `FOR UPDATE`, re-check status → `settle` (top-up, payment, wallet) or, refusing, `cancel_pending` (top-up, payment) |
| cancel (`-9`)  | read the row without a lock → `resolve(row.account, lock=True)` → row `FOR UPDATE`, re-check `PREPARED` → `cancel_pending`                                                                                             |
| `cancel_stale` | scan joins row → payment → top-up `FOR UPDATE OF wallet_topups SKIP LOCKED` → per row (SAVEPOINT) row `FOR UPDATE`, re-check `PREPARED` → `cancel_pending`                                                             |

`test_handlers_lock_the_topup_before_the_click_row` deadlocks if a handler takes the row
first.

## Error codes

| Code | Note                          | When                                                                      |
| ---- | ----------------------------- | ------------------------------------------------------------------------- |
| 0    | `Success`                     | —                                                                         |
| -1   | `SIGN CHECK FAILED!`          | Bad signature, another service, or no secret configured                   |
| -2   | `Incorrect parameter amount`  | Not the top-up's amount in soʻm (or not a number)                         |
| -3   | `Action not found`            | `action` is not 0 (prepare) / 1 (complete)                                |
| -4   | `Already paid`                | Top-up paid; complete replayed; second charge refused (row cancelled)     |
| -5   | `User does not exist`         | `merchant_trans_id` names no top-up                                       |
| -6   | `Transaction does not exist`  | Unknown `merchant_prepare_id`, or it does not match the other identifiers |
| -7   | `Failed to update user`       | Internal error or a failed commit                                         |
| -8   | `Error in request from click` | Missing / non-numeric field, not urlencoded, oversized, not POST          |
| -9   | `Transaction cancelled`       | Top-up expired or reversed; row cancelled; Click sent a negative `error`  |

## Settings

`CSMARKET_CLICK_MERCHANT_ID`, `CSMARKET_CLICK_SERVICE_ID`, `CSMARKET_CLICK_SECRET_KEY`
(redacted from logs), `CSMARKET_CLICK_PAY_URL` (default `https://my.click.uz/services/pay`).
Click is offered only with all three of the first set; otherwise the tile is hidden and
every callback is `-1`.

## Metrics

`csmarket_kassa_rejections_total{provider="click", reason}` (`docs/architecture/metrics.md`) counts
webhooks refused before business logic. Counted: `-1` as `reason="signature"`, `-8` as `"malformed"` (a body that is not Click's form, a
missing or non-numeric field, a stray non-POST), once each, in `routes.py`. Every other code counts nothing.

## Not here

The bot / mini-app service, orders (M4 resolves non-`T` numbers), anti-fraud vetoes,
refunds (Click-side only), email (M4). The Click cabinet setup lives in
`docs/runbooks/kassa-setup.md` (Task 16).
