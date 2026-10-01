# payments

Balance top-ups and the attempts to pay them through a kassa (spec §5, rulings R3–R6,
R10, R11). Builds on `wallet` (credits and reversals go through `wallet.api`); `wallet`
never imports `payments`.

**Owns:** tables `wallet_topups` and `payments` (migration `0007_payments_topups`).

- `wallet_topups` — what the customer pays: `number` (`T` + 7 Crockford chars, unique),
  `user_id`, `amount_uzs numeric(14,0) > 0`, `status` `pending` | `succeeded` | `expired` |
  `reversed`, `idempotency_key` (unique per user), `expires_at`, `payment_id` (the attempt
  that succeeded; `ON DELETE SET NULL`), `succeeded_at`. A top-up is a _payable_, so it
  lives here; the ledger stays in `wallet`.
- `payments` — one attempt to pay a payable through one kassa: `number`, `purpose`
  `topup` | `order` (`topup_id` set iff `topup`; `order_id` gets its key in M4), `user_id`,
  `provider`, `provider_ref` (unique per provider when set), `amount_uzs`, `status`,
  `idempotency_key` (unique when set), `metadata` (kassa event ids, never PII),
  `created_at`, `updated_at`, `succeeded_at`. A top-up has 1..N attempts, at most one live
  (`created`/`pending`) per provider.

**Interface (`api.py`):** `Payment`, `WalletTopup`, `Payable`, `resolve`, `ensure_attempt`,
`mark_pending`, `settle`, `reverse`, `cancel_pending`, `AlreadyPaidError`,
`TopupSpentError`, `move`, `TRANSITIONS`, `LIVE`, `InvalidTransitionError`,
`unclaimed_external_id`, `PaymentGateway`, `available_providers`, `get_gateway`,
`return_url`, `create_topup`, `owned_topup`, `topup_view`, `TopupView`, `expire_stale`.

**Routes:** `routes.py` — `GET /payments/providers` (anonymous) and, under the `/wallet`
prefix, `POST /wallet/topups` and `GET /wallet/topups/{number}` (they live here because
`wallet` never imports `payments`); `dev_routes.py` — `POST /dev/topups/{number}/pay`
(404 unless dev login is active; not in the OpenAPI schema).

## Numbers

Top-ups and orders (M4) share the namespace a kassa sees in its account field. A top-up
number starts with `T`; an order number never does (`core.numbers`). `payable.resolve` tells
them apart by that letter.

## FSM (`fsm.py`, ruling R4)

```text
created ──► pending ──► succeeded ──► refunded
   │           ├──────► failed
   │           └──────► cancelled
   └──► succeeded | failed | cancelled
```

`move(payment, to)` is the only place a status changes; it stamps `updated_at`, and
`succeeded_at` on success. Any other edge raises `InvalidTransitionError` (409).
`created → succeeded` is legal: a kassa may settle without an earlier call we saw.

## Payable resolver (`payable.py`, ruling R5)

`resolve(db, account, *, lock=False) -> Payable` — the one way a kassa's account value
(Click `merchant_trans_id`, Payme `account.order`, Uzum `params.order`) becomes a payable.

| Top-up                         | `payable` | `reason`    |
| ------------------------------ | --------- | ----------- |
| `pending`, before `expires_at` | yes       | `ok`        |
| `pending`, past `expires_at`   | no        | `expired`   |
| `succeeded`                    | no        | `paid`      |
| `expired`                      | no        | `expired`   |
| `reversed`                     | no        | `reversed`  |
| anything else (orders in M4)   | no        | `not_found` |

`lock=True` reads the top-up `FOR UPDATE` (re-read even if already in the session).

## Hooks (`hooks.py`, ruling R6)

Every kassa calls these; nothing else changes money state. They flush; the caller commits.

| Hook                                  | Does                                                                             | Idempotent / refuses                                                                                                                                                                                                                                |
| ------------------------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ensure_attempt(payable=, provider=)` | Reuses the top-up's live attempt of that provider, else inserts a `created` one  | `provider_ref = <provider>:<number>`, suffixed `:<payment id>` when an earlier attempt holds it (`unclaimed_external_id`); `AlreadyPaidError` when the top-up is `paid` or `reversed` (an expired one is allowed — callers check `payable.payable`) |
| `mark_pending(payment=)`              | `created → pending` (the kassa now holds a transaction)                          | no-op if `pending`; `InvalidTransitionError` otherwise                                                                                                                                                                                              |
| `settle(payment=, event_id=)`         | attempt `succeeded`; top-up `succeeded` with `payment_id`; `wallet.credit_topup` | no-op if this attempt already succeeded; `AlreadyPaidError` if the top-up was credited through another attempt                                                                                                                                      |
| `reverse(payment=, event_id=)`        | `wallet.reverse_topup`; attempt `refunded`; top-up `reversed`                    | no-op if `refunded`; `TopupSpentError` if the balance no longer covers it (R7); `InvalidTransitionError` if never paid                                                                                                                              |
| `cancel_pending(payment=)`            | `created`/`pending` → `cancelled`                                                | no-op on any other status — a settled attempt is never pulled back                                                                                                                                                                                  |

- **One credit per top-up**: the ledger key is `topup:{topup_id}`, and `settle` refuses a
  second attempt once the top-up is `succeeded` or `reversed` (the kassa then refuses the
  charge — Click −4, Payme −31051 / −31008, Uzum 10008).
- **Paid after expiry**: `settle` credits an attempt the kassa held even when the top-up's
  `expires_at` has passed — the money arrived. A kassa cannot _start_ paying an expired
  top-up: `resolve` refuses it first.
- **No overdraft**: `reverse_topup` locks the user's wallet and refuses when the balance is
  below the amount; nothing is written and the caller rolls back.
- **Lock order, everywhere: top-up → kassa transaction row → payment → user wallet.** A
  kassa opening an attempt resolves the top-up with `lock=True` before it touches the
  attempt, so every hook that moves an attempt (`mark_pending`, `settle`, `reverse`,
  `cancel_pending`) locks the top-up first too, and so does the expiry sweep. The other
  order deadlocks a create racing a settle
  (`test_settle_and_a_kassa_create_on_one_topup_do_not_deadlock`,
  `test_mark_pending_then_settle_racing_a_kassa_create_do_not_deadlock`).
- `purpose='order'` raises `NotImplementedError` until M4.

**Logs:** `payments.attempt.created`, `payments.topup.created`, `payments.topup.credited`, `payments.topup.reversed`,
`payments.topup.reverse_refused`, `payments.topup.second_payment_refused` — number,
provider and amount only, never the user.

## Top-ups (`topups.py`, owner decision D1, rulings R3, R8, R11)

- `create_topup(db, *, user_id, amount_uzs, provider, idempotency_key, locale)` →
  `(topup, first attempt, intent_url | None)`. Amount: whole soʻm from `topup_min_uzs`
  (1 000) to `topup_max_uzs` (10 000 000), else `ValidationError` `code=topup_amount`.
  Provider: one of `available_providers()` and never `wallet`, else `code=topup_provider`.
  Allocates a `T…` number, `expires_at = now + topup_expiry_minutes` (30), opens the
  first attempt with `ensure_attempt`, and returns the gateway's intent URL.
- **Replays** by `(user_id, idempotency_key)` — the table's own unique, no replay store.
  The same key with the same amount and kassa (the first attempt's provider) returns the
  same top-up; anything else is `ConflictError` `code=idempotency_mismatch` (409). The
  check runs on the pre-read **and** on the race path (two requests with one key: the
  loser's insert fails on the unique once the winner commits, then is held to the same
  rule).
- `owned_topup(db, *, user_id, number)` — `None` for a malformed, unknown or someone
  else's number (the route answers 404, never 403). `topup_view(db, topup, *, locale)` —
  the first attempt's provider and the intent URL while the top-up is payable (`None`
  once paid, expired or reversed, or when that kassa is no longer available).
- `expire_stale(db, *, limit=500)` (R8) — pending top-ups past `expires_at` with no
  attempt in `pending`/`succeeded`, locked `FOR UPDATE SKIP LOCKED` (a kassa mid-create
  holds its top-up: skipped, not waited for). The attempts are re-read after the lock and
  a top-up a kassa got to in between is skipped; every `created` attempt is cancelled via
  `cancel_pending` and the top-up goes `expired`. Attempts a kassa holds are left to that
  kassa's own timeout sweep. Run by the scheduler job `wallet.topup_expiry` every 5
  minutes (first run 140 s after start).
- `dev_pay(db, *, number)` (R11) — `ensure_attempt(mock)` → `mark_pending` → `settle`; a
  no-op once paid; `ConflictError` `code=topup_not_payable` when expired or reversed.

## Gateways (`gateways/`, rulings R10, R11)

A gateway only builds the URL the customer is sent to — `intent_url(payable=, locale=)`;
`ensure_attempt` owns the row and each kassa's callbacks live in its own module.
`registry()` holds every gateway; `available_providers()` lists the available ones in the
order `click, payme, uzum, mock`; `get_gateway(provider)` raises `NotFoundError` (404) for
an unknown or unavailable one. Every intent returns the customer to our own page,
`return_url(number, locale)` = `{web_base_url}[/uz|/en]/account/balance/topups/{number}`
(ru has no prefix) — there is no client-supplied return URL.

`mock` is available everywhere but production; its intent URL is the top-up page with
`?mock=1`, from which the dev-only pay route drives the real `settle`.

`click` (`gateways/click.py`) is available with `click_merchant_id`, `click_service_id` and
`click_secret_key` all set; its intent URL is
`{click_pay_url}?service_id=&merchant_id=&amount=<soʻm>&transaction_param=<number>&return_url=`.
It imports nothing from the `click` module (which imports `payments`).

`payme` (`gateways/payme.py`) is available with `payme_merchant_id` and `payme_key` or
`payme_test_key`; its intent URL is `{payme_checkout_url}/{base64(params)}` with
`params = "m=<merchant id>;ac.order=<number>;a=<tiyin>;c=<our top-up page>;l=<ru|uz|en>"`.
It imports nothing from the `payme` module.

**Tests:** `tests/unit/test_payment_fsm.py`, `tests/unit/test_payment_gateways.py`,
`tests/integration/test_payable_resolver.py`, `tests/integration/test_payment_hooks.py`
(including real races: two kassas settling one top-up, a create racing a settle, a create
racing `mark_pending` + `settle`), `tests/integration/test_topups.py` (HTTP: create,
limits, providers, replay and the replay race, owner-only read, dev pay),
`tests/integration/test_topup_expiry.py` (the sweep, R8).
`tests/integration/payments_factory.py` makes users and top-ups for the payments suites.
