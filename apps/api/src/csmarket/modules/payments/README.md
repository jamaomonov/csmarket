# payments

Balance top-ups, and the attempts to pay a top-up or an order (M4a) through a kassa (spec
§5, rulings R3–R6, R10, R11; ADR-0006; M4a ruling R7). Builds on `wallet` (credits and
reversals go through `wallet.api`) and reaches orders only through `orders.api` (a settled
order attempt calls `orders.mark_paid`); neither `wallet` nor `orders.api` imports
`payments` (`test_orders_api_never_imports_payments`). Operations: `docs/runbooks/kassa-setup.md`; flow:
`docs/product/flows/balance-topup.md`.

**Owns:** tables `wallet_topups` and `payments` (migration `0007_payments_topups`;
`0012_payments_number_pattern_ops` rebuilds `ix_payments_number` with `text_pattern_ops` so
the admin search's prefix `LIKE` uses it under any collation; `0014_payments_order_id_idx`
adds `ix_payments_order` — an order's attempts are found by `order_id`).

- `wallet_topups` — what the customer pays: `number` (`T` + 7 Crockford chars, unique),
  `user_id`, `amount_uzs numeric(14,0) > 0`, `status` `pending` | `succeeded` | `expired` |
  `reversed`, `idempotency_key` (unique per user), `expires_at`, `payment_id` (the attempt
  that succeeded; `ON DELETE SET NULL`), `succeeded_at`. A top-up is a _payable_, so it
  lives here; the ledger stays in `wallet`.
- `payments` — one attempt to pay a payable through one kassa: `number`, `purpose`
  `topup` | `order` (`topup_id` set iff `topup`, `order_id → orders` set iff `order` —
  migration `0013_orders_skin_trades`), `user_id`, `provider` (a kassa slug, or `wallet` for
  an order paid from the balance — never a registered gateway), `provider_ref` (unique per
  provider when set), `amount_uzs`, `status`, `idempotency_key` (unique when set),
  `metadata` (kassa event ids, never PII),
  `created_at`, `updated_at`, `succeeded_at`. A top-up or an order (its _owner_) has 1..N
  attempts, at most one live (`created`/`pending`) per provider.

**Interface (`api.py`):** `Payment`, `WalletTopup`, `Payable`, `resolve`, `ensure_attempt`,
`mark_pending`, `settle`, `reverse`, `cancel_pending`, `lock_owner_or_skip`, `Owner`,
`AlreadyPaidError`, `ReversalRefusedError`, `TopupSpentError`, `OrderReversalRefusedError`,
`move`, `TRANSITIONS`, `LIVE`, `InvalidTransitionError`,
`unclaimed_external_id`, `PaymentGateway`, `available_providers`, `get_gateway`,
`return_url`, `create_topup`, `owned_topup`, `topup_view`, `TopupView`, `expire_stale`.

**Routes:** `routes.py` — `GET /payments/providers` (anonymous) and, under the `/wallet`
prefix, `POST /wallet/topups` and `GET /wallet/topups/{number}` (they live here because
`wallet` never imports `payments`); `dev_routes.py` — `POST /dev/topups/{number}/pay`
(404 unless dev login is active — `api.v1.deps.dev_gate`, shared with `orders.dev_routes`;
not in the OpenAPI schema). An order's pay route (`POST /orders/{number}/pay`) lives in
`orders`: it opens attempts here through `resolve` + `ensure_attempt` + `get_gateway`, and
writes the balance's `provider="wallet"` row itself (ruling R8).

## Numbers

Top-ups and orders (M4a) share the namespace a kassa sees in its account field. A top-up
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

A `T…` number is a top-up, any other well-formed number an order (`kind="order"`,
`Payable.order` set, `amount_uzs = order.price_uzs`, `user_id = order.user_id`).

| Top-up                         | `payable` | `reason`   |
| ------------------------------ | --------- | ---------- |
| `pending`, before `expires_at` | yes       | `ok`       |
| `pending`, past `expires_at`   | no        | `expired`  |
| `succeeded`                    | no        | `paid`     |
| `expired`                      | no        | `expired`  |
| `reversed`                     | no        | `reversed` |

| Order                                                             | `payable` | `reason`  |
| ----------------------------------------------------------------- | --------- | --------- |
| `pending`, before `expires_at`                                    | yes       | `ok`      |
| `pending`, past `expires_at`; `cancelled`                         | no        | `expired` |
| `paid`, `buying`, `trade_sent`, `delivered`, `failed`, `returned` | no        | `paid`    |

An unknown or malformed number is `not_found` (amount 0, no owner). `lock=True` reads the
top-up or order `FOR UPDATE` (re-read even if already in the session). The kassas'
`_REFUSALS` tables key on `reason`, so an order is refused exactly like a top-up: paid →
Click −4 / Payme −31051 / Uzum 10008, expired → Click −9 / Payme −31051 / Uzum 10009.

## Hooks (`hooks.py`, ruling R6)

Every kassa calls these; nothing else changes money state. They flush; the caller commits.
An attempt's _owner_ is its top-up or its order.

| Hook                                  | Does                                                                                                                                                                         | Idempotent / refuses                                                                                                                                                                                                                                                               |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ensure_attempt(payable=, provider=)` | Reuses the owner's live attempt of that provider, else inserts a `created` one (an order's: `purpose="order"`, `order_id`, `amount_uzs = price_uzs`)                         | `provider_ref = <provider>:<number>`, suffixed `:<payment id>` when an earlier attempt holds it (`unclaimed_external_id`); `AlreadyPaidError` when the payable is `paid` or `reversed` (an expired one is allowed — callers check `payable.payable`); `ValueError` for `not_found` |
| `mark_pending(payment=)`              | `created → pending` (the kassa now holds a transaction)                                                                                                                      | no-op if `pending`; `InvalidTransitionError` otherwise                                                                                                                                                                                                                             |
| `settle(payment=, event_id=)`         | attempt `succeeded`; a top-up `succeeded` with `payment_id` + `wallet.credit_topup`; an order `orders.mark_paid` (`paid`, `paid_with` = provider, `NOTIFY orders` on commit) | no-op if this attempt already succeeded (no second `NOTIFY`); `AlreadyPaidError` if the top-up was credited through another attempt, or the order is no longer `pending`                                                                                                           |
| `reverse(payment=, event_id=)`        | a top-up: `wallet.reverse_topup`; attempt `refunded`; top-up `reversed`                                                                                                      | no-op if `refunded`; `TopupSpentError` if the balance no longer covers it; `OrderReversalRefusedError` for any order payment (R7); `InvalidTransitionError` if never paid. Both refusals are `ReversalRefusedError` (Payme −31007, Uzum 10017)                                     |
| `cancel_pending(payment=)`            | `created`/`pending` → `cancelled` (an order stays `pending`: its expiry sweep owns it)                                                                                       | no-op on any other status — a settled attempt is never pulled back                                                                                                                                                                                                                 |
| `lock_owner_or_skip(payment_id=)`     | locks the attempt's owner `FOR UPDATE SKIP LOCKED` (the kassas' timeout sweeps)                                                                                              | `False` when a callback holds the owner — the sweep skips that row until its next tick                                                                                                                                                                                             |

- **One credit per top-up**: the ledger key is `topup:{topup_id}`, and `settle` refuses a
  second attempt once the top-up is `succeeded` or `reversed` (the kassa then refuses the
  charge — Click −4, Payme −31051 / −31008, Uzum 10008).
- **Paid after expiry**: `settle` credits an attempt the kassa held even when the top-up's
  `expires_at` has passed — the money arrived. A kassa cannot _start_ paying an expired
  top-up: `resolve` refuses it first.
- **One payment per order**: `settle` refuses an attempt once the order left `pending`, so
  a second kassa's charge is refused (Click −4, Payme −31008, Uzum 10008) and the worker
  hears one `NOTIFY orders` per order. A kassa-paid order books nothing on the balance.
- **A kassa never reverses an order** (R7): the skin is bought at payment and refunds go
  to the balance, so `reverse` raises `OrderReversalRefusedError` before touching anything.
- **No overdraft**: `reverse_topup` locks the user's wallet and refuses when the balance is
  below the amount; nothing is written and the caller rolls back.
- **Lock order, everywhere: owner (top-up or order) → kassa transaction row → payment →
  user wallet.** A kassa opening an attempt resolves the owner with `lock=True` before it
  touches the attempt, so every hook that moves an attempt (`mark_pending`, `settle`,
  `reverse`, `cancel_pending`) locks the owner first too (`_lock_owner_then_payment`), and
  so do the expiry sweep and the kassas' timeout sweeps (`lock_owner_or_skip`). The other
  order deadlocks a create racing a settle
  (`test_settle_and_a_kassa_create_on_one_topup_do_not_deadlock`,
  `test_mark_pending_then_settle_racing_a_kassa_create_do_not_deadlock`,
  `test_settle_and_a_kassa_create_on_one_order_do_not_deadlock`).

**Logs:** `payments.attempt.created`, `payments.topup.created`, `payments.topup.credited`,
`payments.topup.reversed`, `payments.topup.reverse_refused`,
`payments.topup.second_payment_refused`, `payments.order.paid`, `payments.order.second_payment_refused`,
`payments.order.reverse_refused` — number, provider, amount and status only, never the user.

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
  rule). The replay is looked up **before** the provider is checked, so a replayed key
  returns its stored top-up even after that kassa lost its credentials (`intent_url`
  `None`).
- `owned_topup(db, *, user_id, number)` — `None` for a malformed, unknown or someone
  else's number (the route answers 404, never 403). `topup_view(db, topup, *, locale)` —
  the first attempt's provider and the intent URL while the top-up is payable (`None`
  once paid, expired or reversed, or when that kassa is no longer available), and
  `awaiting_kassa(db, topup)`: `pending` with an attempt in `pending` (a kassa holds it and
  may still settle past `expires_at`); the storefront shows "checking" instead of "expired".
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
`return_url(number, locale)` = `{web_base_url}[/uz|/en]/account/balance/topups/{number}` for
a `T…` number and `{web_base_url}[/uz|/en]/orders/{number}` for any other (an order; ru has
no prefix) — there is no client-supplied return URL.

`mock` is available everywhere but production; its intent URL is the payable's page with
`?mock=1`, from which the dev-only pay route drives the real `settle`.

`click` (`gateways/click.py`) is available with `click_merchant_id`, `click_service_id` and
`click_secret_key` all set; its intent URL is
`{click_pay_url}?service_id=&merchant_id=&amount=<soʻm>&transaction_param=<number>&return_url=`.
It imports nothing from the `click` module (which imports `payments`).

`payme` (`gateways/payme.py`) is available with `payme_merchant_id` and a key from
`Settings.payme_keys()` (`payme_key`, or `payme_test_key` outside prod or with
`kassa_sandbox_enabled`); its intent URL is `{payme_checkout_url}/{base64(params)}` with
`params = "m=<merchant id>;ac.order=<number>;a=<tiyin>;c=<our top-up page>;l=<ru|uz|en>"`.
It imports nothing from the `payme` module.

`uzum` (`gateways/uzum.py`) is available with `uzum_service_id` and a whole login/password
pair from `Settings.uzum_pairs()` (production, or sandbox outside prod or with
`kassa_sandbox_enabled`); its intent URL is
`{uzum_open_service_url}?serviceId=<id>&order=<number>&redirectUrl=<our top-up page>` — no
amount: Uzum's app prefills it from our `/check`. It imports nothing from the `uzum` module.

## Not here

Paying an order from the balance (`provider="wallet"`, ruling R8) and the order pay route
live in `orders` (M4a Task 6). Admin "settle a stuck payment", a kassa kill-switch and card
refunds from admin are not planned (ruling R12).

**Tests:** `tests/unit/test_payment_fsm.py`, `tests/unit/test_payment_gateways.py`,
`tests/integration/test_payable_resolver.py`, `tests/integration/test_payment_hooks.py`
(including real races: two kassas settling one top-up, a create racing a settle, a create
racing `mark_pending` + `settle`), `tests/integration/test_topups.py` (HTTP: create,
limits, providers, replay and the replay race, owner-only read, dev pay),
`tests/integration/test_topup_expiry.py` (the sweep, R8); orders (M4a):
`tests/integration/test_payment_hooks_orders.py` (attempt, settle + `NOTIFY`, refusals, the
create/settle race), `test_payments_orders_{click,payme,uzum}.py` (each kassa over HTTP),
`test_kassa_sweeps_orders.py` (the timeout sweeps for both owners, SKIP LOCKED).
`tests/integration/payments_factory.py` makes users and top-ups for the payments suites.
