# uzum

Uzum Bank's Merchant API for balance top-ups and orders (spec §3.2, §13; M3, M4a, ADR-0006), ported by
allow-list (ADR-0002). Uzum does not deliver a webhook: **we are Uzum's Merchant API
server**. Uzum calls five endpoints over the life of a transaction, and **we** own the
transaction state machine — Uzum signals a replay with a dedicated code, not an echo. Every
money move goes through the `payments` hooks; this module never touches `wallet`.

**Owns:** table `uzum_transactions` (migration `0010_uzum_transactions`): `id`, `trans_id`
(`varchar(64)`, unique — Uzum's transaction id, the replay key), `payment_id` (the attempt,
`ON DELETE RESTRICT`), `account` (the top-up or order number Uzum sent), `amount_tiyin BIGINT`,
`status` `CREATED` | `CONFIRMED` | `REVERSED` | `FAILED`, `service_id`, `create_time`
(`BIGINT` epoch ms, ours), `confirm_time` / `reverse_time` (`BIGINT`, `NULL` until set),
`payment_source jsonb`, `created_at`, `updated_at`. Indexes on `payment_id`, `account` and a
partial `(create_time) WHERE status = 'CREATED'` (the timeout sweep's scan).

**Interface (`api.py`):** `UzumTransaction`, `UZUM_STATUSES`, `fail_stale`, `TIMEOUT`,
`PROVIDER`. The gateway (`payments/gateways/uzum.py`, provider `uzum`) builds the checkout
link and needs nothing from this module.

## Endpoints

```text
POST /api/v1/payments/uzum/check
POST /api/v1/payments/uzum/create
POST /api/v1/payments/uzum/confirm
POST /api/v1/payments/uzum/reverse
POST /api/v1/payments/uzum/status
GET|PUT|PATCH|DELETE|HEAD|OPTIONS on any of them   10003 at HTTP 400 (never a 405)
```

- **HTTP 200 on success, HTTP 400 on every error** (Uzum's contract), with
  `{"status": "FAILED", "errorCode", "serviceId", "transId"?}` — `serviceId` and `transId`
  echoed when the body was parsed. Never a 401, 405, 422 or 500: a commit failure is `99999`.
- **Auth, before the body is read:** `Authorization: Basic base64("<login>:<password>")`
  matching one of `Settings.uzum_pairs()`: the production pair (`uzum_login` /
  `uzum_password`) **or** the sandbox pair (`uzum_test_login` / `uzum_test_password`), so one
  endpoint serves both. **In prod the sandbox pair counts only with `kassa_sandbox_enabled`**
  (off by default; startup warns `kassa.sandbox_enabled_in_prod` while it is on). Compared as
  UTF-8 bytes in constant time across the usable pairs; a pair with a blank half never
  matches; a non-ASCII or undecodable credential fails closed. Failure → `10001`.
- **Body:** a JSON object of at most 64 KiB (read with a bound, `core.request_body`), else
  `10002` — also for a body nested deeply enough to raise `RecursionError`.
- **`serviceId`:** must be exactly the configured `uzum_service_id` (an integer, not a
  string, float or `true`); otherwise, or with none configured, `10006`.
- **Fields:** `transId` a string of 1..64; `amount` an integer (not `bool`, not a float);
  `params` an object with the account → else `10005`.
- Exempt from slowapi (`bootstrap._exempt_self_authenticating_routes`, all five). Uzum
  publishes no source range; Basic auth is the gate.
- Logs: `uzum.callback endpoint= code= number= amount_tiyin=` (code `0` = success) and
  `uzum.created|confirmed|reversed`, `uzum.confirm.second_charge_refused number= amount=` —
  never the Authorization header, a password, the body, a user id or `payment_source`
  (`payment_source` is also a redacted log key, and `phone` a redacted stem).

## Amounts and account

- **Tiyin on the wire, soʻm only in `/check`'s `data`.** `amount` on `/create`, `/confirm`,
  `/reverse`, `/status` is tiyin and must equal the top-up's `amount_uzs × 100` (an
  order's `price_uzs × 100`) exactly (the
  soʻm figure is `10011`). `/check` answers `data.amount.value` = whole soʻm as a bare
  integer string (`"50000"`) — Uzum's app prefills the amount from it. Do not unify the
  units: the asymmetry is Uzum's contract.
- **Account field (R9):** `params.order` = the top-up number (`T` + 7) or an order number
  (M4a). `params.orderId`,
  then `params.order_id`, are accepted too (Uzum was seen sending camelCase `orderId` on
  2026-09-04; the field name is configurable per service). The first non-empty string wins;
  none → `10005`.

## The five webhooks

| Endpoint   | Success body (plus `serviceId`)                                                                   | Errors                                                              |
| ---------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `/check`   | `{"timestamp": <our response time, ms>, "status": "OK", "data": {"amount": {"value": "<soʻm>"}}}` | `10007` unknown, `10008` paid, `10009` expired / reversed           |
| `/create`  | `{"transId", "status": "CREATED", "transTime", "amount"}`                                         | `10010` replay; as `/check`; `10011` amount                         |
| `/confirm` | `{"transId", "status": "CONFIRMED", "confirmTime", "amount"}`                                     | `10014` unknown, `10016` replay, `10015` reversed / failed, `10008` |
| `/reverse` | `{"transId", "status": "REVERSED", "reverseTime", "amount"}`                                      | `10014` unknown, `10018` replay, `10017` the top-up was spent       |
| `/status`  | `{"transId", "status", "transTime", "confirmTime", "reverseTime", "data": {}, "amount"}`          | `10014` unknown                                                     |

`data` comes only from `/check` and `/status` (Uzum's engineer, 2026-07-24). `/status` is
Uzum's reconciliation channel: after a `/confirm` whose answer it lost, it polls up to 10
times; `/confirm` commits before it answers, so `/status` always sees `CONFIRMED`.

**`/create` replay, including another account's `transId` (ruling 2):** any `transId` we
already hold is `10010` — Uzum's own "already created" code, the nearest fit for an id that
belongs to another top-up too. The existing row is only **read**, never locked: we hold the
caller's top-up, not necessarily the row's, and the answer does not depend on the row's
state. No attempt is opened for the caller's top-up.

`/confirm` stores everything it was sent except `serviceId`, `timestamp`, `transId` in
`payment_source` (`paymentSource`, `tariff`, `processingReferenceNumber`, `phone`,
`cardType`, …) — the payer's phone is in it, so it is never logged and admin shows it masked
(`admin.payments_kassa.mask_phone`).

## State machine

```text
/create  → CREATED
CREATED   --/confirm--> CONFIRMED   settle: the attempt succeeds, the top-up is credited once
CREATED   --/reverse--> REVERSED    the attempt is released (unless another CREATED row holds it)
CONFIRMED --/reverse--> REVERSED    reverse: the top-up is clawed back if unspent, else 10017
CREATED   --30 min----> FAILED      the timeout sweep; the attempt is released likewise
CREATED   --/confirm after the top-up was credited elsewhere--> FAILED, answer 10008
FAILED    --/reverse--> REVERSED    the row closes; its attempt was released when it failed
```

### One payment per top-up or order

The account is a top-up or an order — its _owner_; an order is refused like a top-up (the
refusals key on `payable.reason`).

- `/check` / `/create` on a paid top-up or order → `10008`; expired or reversed (an order
  past its window, or cancelled) → `10009`.
- **`/confirm` after the owner was paid elsewhere** (another kassa, or a sibling Uzum row
  sharing this attempt) → `10008`, and the transaction is **FAILED and committed**
  (`UzumError.persist`), so Uzum drops this charge and `/status` reports `FAILED`.
- **`/reverse` of a confirmed top-up** → `REVERSED` and `payments.reverse` (`topup_reversal`)
  when the amount is still on the balance; otherwise `10017` and nothing changes (ruling R7,
  logged `payments.topup.reverse_refused`). Refunds start on Uzum's side; there is no
  merchant-initiated refund.
- **`/reverse` of a confirmed order** → `10017` and nothing changes (ruling R7: the skin is
  bought at payment and refunds go to the balance; `payments.reverse` raises
  `OrderReversalRefusedError`, caught as `ReversalRefusedError`). A `CREATED` order row
  reverses normally and the order stays `pending`.
- **A retried checkout** (a second `/create` with a new `transId` on a top-up Uzum already
  holds) shares the live attempt. Releasing it (reverse, sweep, a refused second charge)
  cancels the attempt only when no other `CREATED` Uzum row holds it, and `cancel_pending`
  never pulls a settled attempt back.
- **Retry after a declined card:** the reversed attempt keeps `uzum:<number>` and the new
  attempt gets `uzum:<number>:<id>` (`payments.external_ids`), so the retry is never a `99999`.
- **Insert race:** two first-time `/create`s with one `transId` lock their own top-ups and
  both reach the insert. `ensure_attempt`, `mark_pending` and the insert share one
  SAVEPOINT; the loser's attempt work is undone and it answers `10010`.

## Lock order

Global: **owner (top-up or order) → Uzum row → payment → user wallet.** "top-up" below
reads "owner".

| Handler               | Sequence                                                                                                                                                                                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/check`              | `resolve(account, lock=True)` (top-up)                                                                                                                                                                                                                          |
| `/create`             | `resolve(account, lock=True)` → row by `transId`, **unlocked** read (replay → `10010`) → payable / amount → SAVEPOINT { `ensure_attempt` → `mark_pending` (top-up, payment) → insert }                                                                          |
| `/confirm`/`/reverse` | read the row by `transId` **without** a lock → `resolve(row.account, lock=True)` → row `FOR UPDATE` (populate_existing), re-check status → payment → `settle` / `reverse` / release                                                                             |
| `/status`             | plain read, no lock                                                                                                                                                                                                                                             |
| `fail_stale`          | unlocked scan of stale `CREATED` rows (top-up and order attempts) → per row (SAVEPOINT) `lock_owner_or_skip` (owner `FOR UPDATE SKIP LOCKED`; held → next tick) → row `FOR UPDATE`, re-check `CREATED` → `FAILED` + release; an order's status is never touched |

`test_handlers_lock_the_topup_before_the_uzum_row` deadlocks if a handler takes the row first.

## Timeout

The scheduler job `uzum.timeout` (every 5 min, first run after 200 s) runs `fail_stale`:
`CREATED` rows whose `create_time` is older than 30 min (Uzum's spec §10) go `FAILED` and
their attempt is released; the top-up expiry sweep then closes the top-up. A row whose top-up
a callback holds is skipped until the next tick; one failing row is logged
(`uzum.timeout.row_failed`) and skipped. A `CONFIRMED` row is never in scope.

## Error codes

| Code    | When                                                                                 |
| ------- | ------------------------------------------------------------------------------------ |
| `10001` | Basic auth failed                                                                    |
| `10002` | Body is not a JSON object (or over 64 KiB, or too deeply nested)                     |
| `10003` | Not POST                                                                             |
| `10005` | A required field is missing or mistyped                                              |
| `10006` | `serviceId` is not ours, or none is configured                                       |
| `10007` | Unknown top-up or order number                                                       |
| `10008` | Top-up / order already paid; at `/confirm`, a second charge (the transaction FAILED) |
| `10009` | Top-up / order expired, top-up reversed, order cancelled                             |
| `10010` | `transId` already created (any account)                                              |
| `10011` | Amount is not the top-up's / order's × 100 (tiyin)                                   |
| `10012` | Below minimum — reserved, not raised (the top-up's own amount is checked)            |
| `10013` | Above maximum — reserved, not raised                                                 |
| `10014` | Unknown `transId`                                                                    |
| `10015` | `/confirm` on a REVERSED or FAILED transaction                                       |
| `10016` | `/confirm` replay on a CONFIRMED transaction                                         |
| `10017` | `/reverse` of a CONFIRMED top-up whose money was spent, or of a CONFIRMED order      |
| `10018` | `/reverse` replay on a REVERSED transaction                                          |
| `99999` | Internal error or a failed commit                                                    |

## Settings

`CSMARKET_UZUM_SERVICE_ID`, `CSMARKET_UZUM_LOGIN`, `CSMARKET_UZUM_PASSWORD`,
`CSMARKET_UZUM_TEST_LOGIN`, `CSMARKET_UZUM_TEST_PASSWORD` (both passwords redacted from
logs), `CSMARKET_UZUM_OPEN_SERVICE_URL` (default `https://uzumbank.uz/open-service`). Uzum is
offered with the service id and a whole usable pair (the sandbox pair in prod only with
`CSMARKET_KASSA_SANDBOX_ENABLED=true`); otherwise the tile is hidden and every call is
`10001` (or `10006` without a service id). The checkout link is
`{open_service_url}?serviceId=<id>&order=<number>&redirectUrl=<our top-up page>` — no amount.

## Metrics

`csmarket_kassa_rejections_total{provider="uzum", reason}` (`docs/architecture/metrics.md`) counts
webhooks refused before business logic. Counted: `10001` as `reason="auth"`; `10002` (including a
body over 64 KiB or a `RecursionError` body) and `10005` as `"malformed"`, once each, in `routes.py`. Every other code
counts nothing.

## Not here

Anti-fraud vetoes, card refunds from admin (Uzum's side
only), email (M4b). Postman collection for Uzum's engineer: `docs/api/uzum.postman_collection.json`.
Order tests: `tests/integration/test_payments_orders_uzum.py`,
`tests/integration/test_kassa_sweeps_orders.py`. Cabinet setup (including
the `order` attribute name): `docs/runbooks/kassa-setup.md`; troubleshooting:
`docs/runbooks/uzum.md`.
