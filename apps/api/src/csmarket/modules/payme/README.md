# payme

Payme's Merchant API for balance top-ups and orders (spec §3.2, §13; M3, M4a, ADR-0006), ported by allow-list
(ADR-0002). Payme does not deliver a webhook: **we are Payme's JSON-RPC server**. Payme calls
seven methods on one endpoint over the life of a transaction, and its transaction record is
mirrored here. Every money move goes through the `payments` hooks; this module never touches
`wallet`.

**Owns:** table `payme_transactions` (migration `0009_payme_transactions`): `id`, `payme_id`
(`varchar(64)`, unique — Payme's transaction id, the replay key), `payment_id` (the attempt,
`ON DELETE RESTRICT`), `account` (the top-up or order number Payme sent), `amount_tiyin BIGINT`,
`state` `1` | `2` | `-1` | `-2`, `reason`, `create_time` / `perform_time` / `cancel_time`
(`BIGINT` epoch ms, `0` until set), `fiscal_data jsonb`, `created_at`, `updated_at`. Indexes
on `payment_id`, `account` and `(state, create_time)` (the timeout sweep's scan).

**Interface (`api.py`):** `PaymeTransaction`, `PAYME_STATES`, `cancel_stale`, `TIMEOUT`,
`PROVIDER`. The gateway (`payments/gateways/payme.py`, provider `payme`) builds the checkout
link and needs nothing from this module.

## Endpoint

```text
POST /api/v1/payments/payme/merchant    JSON-RPC 2.0: {"method", "params", "id"}
GET|PUT|PATCH|DELETE|HEAD|OPTIONS       -32300 (never a 405)
```

- **Always HTTP 200**: `{"result": …, "id"}` or
  `{"error": {"code", "message": {"ru", "uz", "en"}, "data"}, "id"}`. Payme reads any other
  status as `-32400`. A commit failure is `-32400`, never a 500. The request `id` is echoed
  (`null` when the body was not parsed).
- **Auth, before the body is read:** `Authorization: Basic base64("Paycom:<key>")`. The login
  is `payme_login` (default `Paycom`); the key is one of `Settings.payme_keys()`: `payme_key`
  (production) **or** `payme_test_key` (sandbox), so one endpoint serves the sandbox and live
  traffic. **In prod the test key counts only with `kassa_sandbox_enabled`** (off by default;
  startup warns `kassa.sandbox_enabled_in_prod` while it is on): a sandbox key must never
  credit a real balance. Compared as UTF-8 bytes in constant time across the usable keys; a
  blank configured key never matches; a non-ASCII or undecodable credential fails closed.
  Failure → `-32504`.
- Parameters are checked by type (`amount`, `time`, `reason`, `from`, `to` integers — not
  `bool`, not floats; `id` a string of 1..64; `account`, `fiscal_data` objects) → `-32600`.
- Exempt from slowapi (`bootstrap._exempt_self_authenticating_routes`). Payme's source range
  `185.234.113.0/28` is enforced at Caddy (`infra/caddy/Caddyfile.prod`) on top of Basic auth.
- Logs: `payme.rpc method= code= number= amount_tiyin=` (code `0` = success) and
  `payme.created|performed|cancelled number= amount=` — never the Authorization header, a
  key, the body or a user id.

## Amounts and account

- Payme speaks **tiyin**: the amount must equal the top-up's `amount_uzs × 100` (an
  order's `price_uzs × 100`) exactly;
  the soʻm figure itself is `-31001`.
- The account field is **`order`** (R9): `params.account.order` = the top-up number
  (`T` + 7) or an order number (M4a). The checkout link sends it as `ac.order`; `GetStatement` rows carry
  `account: {"order": <number>}`. Missing, blank or non-string → `-31050` with `data: "order"`.

## The seven methods

| Method                    | Result                                                                                                                                                                | Errors                                                                                                   |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `CheckPerformTransaction` | `{"allow": true}`                                                                                                                                                     | `-31050` unknown, `-31051` paid / expired / reversed, `-31001` amount                                    |
| `CreateTransaction`       | `{"create_time", "transaction", "state": 1}`                                                                                                                          | as Check; `-31099` another state-1 transaction holds the top-up or order; `-31008` id of another account |
| `PerformTransaction`      | `{"transaction", "perform_time", "state": 2}`                                                                                                                         | `-31003` unknown; `-31008` cancelled, or a second charge (below); `-31051` the order was cancelled       |
| `CancelTransaction`       | `{"transaction", "cancel_time", "state": -1 \| -2}`                                                                                                                   | `-31003` unknown; `-31007` the top-up was spent, or a performed order (R7)                               |
| `CheckTransaction`        | `{create_time, perform_time, cancel_time, transaction, state, reason}`                                                                                                | `-31003`                                                                                                 |
| `GetStatement`            | `{"transactions": [{id, time, amount, account, create_time, perform_time, cancel_time, transaction, state, reason, receivers: []}]}` by `create_time` in `[from, to]` | —                                                                                                        |
| `SetFiscalData`           | `{"success": true}`; keeps the receipt under its `type` (`PERFORM` / `CANCEL`)                                                                                        | `-32001` unknown transaction                                                                             |

`transaction` is our row id. Replays echo: Create returns the stored row whatever its state
(a late replay after the top-up was paid still answers; another amount is `-31001`),
Perform on state 2 and Cancel on `-1` / `-2` return the stored result.

## State machine

```text
Create → 1
  1 --Perform--> 2      settle: the attempt succeeds, the top-up is credited once
                        (an order: moved to paid, NOTIFY orders)
  1 --Cancel---> -1     the attempt is cancelled (unless another state-1 row holds it)
  2 --Cancel---> -2     reverse: the top-up is clawed back if unspent, else -31007
                        (an order: always -31007, R7)
  1 --12 h-----> -1     reason 4, the timeout sweep
  1 --Perform after the owner was paid elsewhere--> -1, reason 3, answer -31008
```

`reason` is Payme's code, stored as sent; we set **4** (timeout) in the sweep and **3**
(execution error) when Perform refuses a second charge.

### One payment per top-up or order

The account is a top-up or an order — its _owner_; an order is refused like a top-up (the
refusals key on `payable.reason`).

- Check / Create on a paid top-up or order → `-31051`; on an expired top-up or order (or a
  cancelled order) → `-31051`.
- **Perform after the owner was paid elsewhere** (another kassa, or a sibling Payme row
  sharing this attempt) → `-31008`, and the transaction is **cancelled and committed**
  (state `-1`, reason `3`, `PaymeError.persist`), so Payme drops this charge instead of
  retrying it. (Ruling: reason 3, Payme's "execution error".) **Perform after the order
  was cancelled** (a held attempt cannot normally outlive the order, but any cancel is
  refused) → `-31051` the same way (cancelled and committed): the account is no longer
  payable, not "already paid".
- **Cancel of a performed top-up** → `-2` and `payments.reverse` (`topup_reversal`) when the
  amount is still on the balance; otherwise `-31007` and nothing changes (ruling R7, logged
  `payments.topup.reverse_refused`). Refunds start in Payme's cabinet; there is no
  merchant-initiated refund.
- **Cancel of a performed order** → `-31007` and nothing changes (ruling R7: the skin is
  bought at payment and refunds go to the balance; `payments.reverse` raises
  `OrderReversalRefusedError`, caught as `ReversalRefusedError`). A state-1 order
  transaction cancels normally and the order stays `pending`.
- A cancel releases the attempt only when no other state-1 Payme row holds it, and
  `cancel_pending` never pulls a settled attempt back.
- **Retry after a declined card** (the port's 2026-09-29 incident): Payme cancels the first
  transaction (reason 2), the buyer pays again, Payme opens a new one; the cancelled attempt
  keeps `payme:<number>` and the new attempt gets `payme:<number>:<id>`
  (`payments.external_ids`), so the retry is never a `-32400`.
- **Insert race:** two first-time Creates with one `payme_id` but different accounts lock
  different top-ups. `ensure_attempt`, `mark_pending` and the insert share one SAVEPOINT;
  the loser's attempt work is undone and it answers `-31008` (or the winner's result when the
  accounts match).

## Lock order

Global: **owner (top-up or order) → Payme row → payment → user wallet.** "top-up" below
reads "owner".

| Handler                          | Sequence                                                                                                                                                                                                                                                  |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CheckPerform                     | `resolve(account.order, lock=True)` (owner)                                                                                                                                                                                                               |
| Create                           | `resolve(account.order, lock=True)` → row by `payme_id` `FOR UPDATE` (replay) → busy check → SAVEPOINT { `ensure_attempt` → `mark_pending` (owner, payment) → insert }                                                                                    |
| Perform / Cancel / SetFiscalData | read the row by `payme_id` **without** a lock → `resolve(row.account, lock=True)` → row `FOR UPDATE` (populate_existing), re-check state → `settle` / `reverse` / `cancel_pending`                                                                        |
| CheckTransaction / GetStatement  | plain reads, no lock                                                                                                                                                                                                                                      |
| `cancel_stale`                   | unlocked scan of stale state-1 rows (top-up and order attempts) → per row (SAVEPOINT) `lock_owner_or_skip` (owner `FOR UPDATE SKIP LOCKED`; held → next tick) → row `FOR UPDATE`, re-check state 1 → `cancel_pending`; an order's status is never touched |

`test_handlers_lock_the_topup_before_the_payme_row` deadlocks if a handler takes the row
first.

## Timeout

The scheduler job `payme.timeout` (every 5 min, first run after 180 s) runs
`cancel_stale`: state-1 rows whose `create_time` is older than 12 h go to `-1`, reason 4,
and their attempt is cancelled; the owner's expiry sweep (top-up or order) then closes the
owner. A row whose owner a callback holds is skipped until the next tick; one failing row is logged
(`payme.timeout.row_failed`) and skipped. A PerformTransaction on a state-1 row older than
12 h that the sweep has not reached yet still settles — the customer paid, so the credit is
safe, and the sweep closes the window within 5 minutes.

## Error codes

| Code     | When                                                                          |
| -------- | ----------------------------------------------------------------------------- |
| `-31001` | Amount is not the top-up's / order's × 100 (tiyin)                            |
| `-31003` | Unknown transaction id                                                        |
| `-31007` | Cancel of a performed top-up whose money was spent, or of a performed order   |
| `-31008` | Perform on a cancelled transaction; a second charge; another account's id     |
| `-31050` | `account.order` missing or unknown (`data: "order"`)                          |
| `-31051` | Top-up / order paid, expired, reversed or cancelled (`data: "order"`)         |
| `-31099` | Another state-1 Payme transaction holds the top-up or order (`data: "order"`) |
| `-32001` | `SetFiscalData` for an unknown transaction                                    |
| `-32300` | Not POST                                                                      |
| `-32400` | Internal error or a failed commit                                             |
| `-32504` | Basic auth failed                                                             |
| `-32600` | Bad envelope or a missing / mistyped parameter                                |
| `-32601` | Unknown method                                                                |
| `-32700` | Body is not JSON, or over 64 KiB                                              |

Messages are trilingual (ru / uz / en); Uzbek uses ʻ (U+02BB).

## Settings

`CSMARKET_PAYME_MERCHANT_ID`, `CSMARKET_PAYME_KEY`, `CSMARKET_PAYME_TEST_KEY` (both keys
redacted from logs), `CSMARKET_PAYME_LOGIN` (default `Paycom`), `CSMARKET_PAYME_CHECKOUT_URL`
(default `https://checkout.paycom.uz`; `https://test.paycom.uz` for the sandbox),
`CSMARKET_KASSA_SANDBOX_ENABLED` (prod only; default `false`). Payme is offered with the
merchant id and a usable key (the production key, or the test key outside prod / with the
opt-in); otherwise the tile is hidden and every call is `-32504`.

## Metrics

`csmarket_kassa_rejections_total{provider="payme", reason}` (`docs/architecture/metrics.md`)
counts webhooks refused before business logic. Counted: `-32504` as `reason="auth"`; `-32700` (bad
JSON, including a body over 64 KiB or nested deeply enough to raise `RecursionError`) and `-32600` (envelope or a
handler's parameter extractor) as `"malformed"`, once each, in `routes.py`. Every other code
counts nothing.

## Not here

Anti-fraud vetoes, card refunds from admin (Payme's cabinet only), email (M4).
Order tests: `tests/integration/test_payments_orders_payme.py`,
`tests/integration/test_kassa_sweeps_orders.py`. Cabinet setup:
`docs/runbooks/kassa-setup.md`; troubleshooting: `docs/runbooks/payme.md`.
