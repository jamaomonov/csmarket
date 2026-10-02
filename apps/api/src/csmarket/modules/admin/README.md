# admin

The admin role gate, the admin audit trail and the admin users API. M1 shipped the gate and
one probe, `GET /api/v1/admin/me`; M2 adds `admin_audit_log` with the first admin actions
(hiding a catalogue item, editing search aliases — `skins/README.md`, **Admin catalogue**);
M3 adds the users list and card, ban/unban and the audited balance adjustment; M4a the
orders and trades API (search, the order page, the attention queue, resolve / refund /
retry — operator steps in `docs/runbooks/orders.md`, design in ADR-0007).

## Role model

- Roles live in `users.roles` (`text[]`, spec §5). The only role is `admin`, matched
  case-sensitively by `deps.has_role`.
- There is no separate admin account: an admin is a normal Steam sign-in whose user row
  carries `admin`. No passwords anywhere.
- Roles are read from the database on every request, so a grant or revoke takes effect on
  the next request; the access token carries no role claim.

## 401 vs 403

- No or invalid token: `401` (from `auth.api.current_user`).
- Banned account: `403 account-suspended` (from `current_user`).
- Signed in without `admin`: `403` "admin role required" — the admin SPA tells "sign in"
  from "not allowed" by this split.

## Granting access

The person signs in with Steam once (creating the row), then on the server:

```bash
docker compose exec api python -m csmarket.scripts.grant_admin --steam-id 7656119XXXXXXXXXX
docker compose exec api python -m csmarket.scripts.grant_admin --steam-id 7656119XXXXXXXXXX --revoke
```

It prints one word — `granted`, `revoked`, `unchanged` or `not_found` (exit code 1) — and
never the Steam ID, because shell history and logs are not a place for it. A malformed ID
exits 2.

## Audit log (M2)

Every admin write records one `admin_audit_log` row (spec §5, ruling Q5), migration
`0005_admin_audit_log`:

| Column          | Type          | Notes                                                     |
| --------------- | ------------- | --------------------------------------------------------- |
| `id`            | uuid pk       |                                                           |
| `actor_user_id` | uuid not null | FK `users.id` — the admin who acted                       |
| `action`        | varchar(64)   | dotted `<module>.<thing>.<verb>`, e.g. `skins.item.hide`  |
| `target_type`   | varchar(32)   | `skin_item`, `skin_alias`, …                              |
| `target_id`     | varchar(64)   | the target's id or natural key                            |
| `payload`       | jsonb         | default `{}`; flat scalars naming things (slugs, aliases) |
| `created_at`    | timestamptz   | default `now()`; indexed, plus `(target_type, target_id)` |

- **Writing:** `admin.api.record(db, *, actor_id, action, target_type, target_id, payload=None)`
  adds the row and flushes; the caller commits it in the same transaction as the change.
- **No PII:** payloads name things (slugs, aliases), never people — no Steam IDs, emails or IPs.
  The actor is the `actor_user_id` column, not a payload field.
- **Replays write nothing:** a write repeated with the same `Idempotency-Key` returns the stored
  response before the handler runs, so it never adds a second row.
- **Actions so far:** `skins.item.hide`, `skins.item.unhide` (`skin_item` / item id,
  `{"slug"}`); `skins.alias.put` (`skin_alias` / alias, `{"alias", "text"}`);
  `skins.alias.delete` (`skin_alias` / alias, `{"alias"}`); M3: `users.ban`, `users.unban`
  (`user` / user id, `{"reason"}`), `wallet.adjust` (`user` / user id,
  `{"amount_uzs", "reason"}` — signed integer soʻm). The reason is the operator's own words.
  M4a (`order` / order number): `orders.trade.resolve` (`{"reason"}` — the attention
  reason), `orders.refund` (`{"amount_uzs"}`), `orders.buy.retry` (`{"reason"}` — the
  attention the retry cleared).
- Read it through `GET /admin/audit` (below), or `make psql`.
- Tests: `tests/integration/test_admin_audit.py`, `test_skins_admin_catalogue.py`.

## Users (M3)

`users_routes.py` (router), `users_service.py` (logic), `users_schemas.py` (wire shapes).
All under `/api/v1/admin/users`, `require_admin` on the router (401 / 403 as above).

| Route                                  | Body                                 | Answer          |
| -------------------------------------- | ------------------------------------ | --------------- |
| `GET /admin/users?q=&cursor=&limit=`   | —                                    | `AdminUsersOut` |
| `GET /admin/users/{id}`                | —                                    | `AdminUserCard` |
| `POST /admin/users/{id}/ban`           | `{reason: 3..500}`                   | `AdminUserCard` |
| `POST /admin/users/{id}/unban`         | `{reason: 3..500}`                   | `AdminUserCard` |
| `POST /admin/users/{id}/wallet/adjust` | `{amount_uzs: ±int, reason: 4..500}` | `AdminUserCard` |

- **List:** newest first, keyset on `(created_at DESC, id DESC)` with an opaque cursor;
  `limit` 1..100 (20). `q` matches the display name (case-insensitive substring, `%` and `_`
  literal) or an exact 17-digit Steam ID. Free-text filters here, on payments and on audit
  go through `filters.text_filter` (a length cap and no NUL byte: asyncpg refuses `\x00`
  in a text parameter, so it is a 422, not a 500). The balance is a correlated subquery
  (`wallet.user_balance_column`): one statement per page, whatever its size.
- **Card:** the profile, the balance, the latest 20 ledger lines (`wallet.entries_for_admin`,
  with `actor` and `reason`) and the latest 20 top-ups. The trade link leaves only masked
  (`users.mask_trade_link`): `partner` kept, the token `••••` + its last 2 characters.
- **Ban:** refuses oneself (`409 ban_self`), an admin (`409 ban_admin` — revoke the role
  first) and a banned account (`409 already_banned`); sets `banned_at`/`ban_reason` and calls
  `auth.revoke_all_sessions` (every refresh row revoked with reason `admin`, its `sid`
  blocklisted). The user's next request and every refresh are `403 account-suspended`.
- **Unban:** `409 not_banned` unless banned; clears both columns. Sessions stay revoked: the
  user signs in again. A stale cookie on another device is then a plain `401`, and it never
  ends the new session (the reuse trip-wire covers only rotated tokens; see `auth/README.md`).
- **Adjust:** `wallet.admin_adjust` — credit D `user_wallet` / C `house_adjustments`,
  clawback the mirror; the user's wallet is locked and a clawback beyond the balance is
  `409 balance_too_low` (ruling R13: never below zero). `amount_uzs` is a JSON integer,
  non-zero, `|x| ≤ 100 000 000`. Ledger key `admin_adjust:<Idempotency-Key>`, actor
  `admin:<admin id>`, metadata `{"reason"}`.
- **Idempotency:** every write requires `Idempotency-Key` (16..160 chars; 422 otherwise).
  Order: lock the target `users` row → replay lookup → change → `audit.record` → replay row
  → commit. The replay row keeps the request it answered (`{request, response}`), so the
  same key on another body or another user is `409 idempotency_mismatch`; a true replay
  returns the stored card and writes nothing. Scopes: `admin.users.ban`, `admin.users.unban`,
  `admin.users.adjust`.
- **Direction:** `admin` imports `users`, `wallet`, `payments` and `auth` (through their
  `api`); none of them imports `admin.users_*` (`tests/unit/test_import_order.py`).
- Tests: `tests/integration/test_admin_users.py`, `test_wallet_admin_adjust.py`.
- Operating the card (reading a history, adjusting with a reason, refused clawbacks):
  `docs/runbooks/wallet.md`; design: ADR-0006.

## Orders and trades (M4a)

`orders_routes.py` (router), `orders_service.py` (reads), `orders_schemas.py` (wire shapes).
The writes are `orders`' own: `orders.admin_actions` (exported by `orders.api`). All under
`/api/v1/admin`, `require_admin` on the router (401 / 403 as above).

| Route                                                             | Body                    | Answer             |
| ----------------------------------------------------------------- | ----------------------- | ------------------ |
| `GET /admin/orders?q=&status=&user_id=&cursor=&limit=`            | —                       | `AdminOrdersOut`   |
| `GET /admin/trades?view=all\|active\|attention&q=&cursor=&limit=` | —                       | `AdminTradesOut`   |
| `GET /admin/orders/{number}`                                      | —                       | `AdminOrderDetail` |
| `POST /admin/orders/{number}/resolve`                             | `{note?: 0..500\|null}` | `AdminOrderDetail` |
| `POST /admin/orders/{number}/refund`                              | —                       | `AdminOrderDetail` |
| `POST /admin/orders/{number}/retry`                               | —                       | `AdminOrderDetail` |

- **Lists:** newest first, keyset `(created_at DESC, id DESC)`, `limit` 1..100 (20); one
  statement per page (the trade and the buyer's name are joins; the trades page adds one
  for the counts). `q` (≤ 100 chars, no NUL) = a number prefix (upper-cased, `%`/`_`
  literal, tried only up to 8 characters) **or** part of the item name (case-insensitive).
  A row's `attention_reason` is the **open** attention only (set, `resolved_at` unset).
- **Trades page:** orders that have a `skin_trades` row. `view=active` = `buying` /
  `trade_sent`; `view=attention` = an unresolved attention; `counts {active, attention}`
  ignore `q`. Each row adds `trade {status (Waxpeer's code), state (the buyer's reading:
buying / offer_sent / accepted / released / failed), attention_reason, send_until}`.
- **Order page:** every `orders` column except `trade_link` (`trade_link_masked` instead) and
  `idempotency_key`,
  `cost_usd` / `price_usd` (6 decimals), `fx_rate` (the snapshot's rate), `margin_usd` =
  `price_usd` − what Waxpeer charged (`bought_units` / 1000), else − `cost_usd`; the buyer
  `{id, display_name}`; the trade (every column an operator needs, `offer_url` built from
  `trade_id`; `attention_reason` whether resolved or not); the payment attempts, oldest
  first; `can_refund`, `can_retry`.
- **`can_refund` / `can_retry`** are `orders.api.can_refund` / `can_retry` — the same
  functions (`refund_refusal`, `retry_refusal`) the actions run under the locks, so the
  button and the action agree (`test_the_flags_say_what_the_action_does`).
- **Resolve («Разобрано»):** stamps `resolved_at`, `resolved_by` (admin id),
  `resolved_note` once; an already resolved attention stays as it was (200, no audit row).
  409 `nothing_to_resolve` without a trade or an attention.
- **Refund:** only a `buying`, unrefunded order whose trade carries a **resolved**
  `buy_unconfirmed`, `ambiguous_trade` or `waxpeer_forbidden` (an operator checked Waxpeer:
  nothing was bought), no purchase on record (`waxpeer_id`) unless our own trade failed
  (status 6), and no running buy attempt. The route checks the replay row unlocked, then
  `orders.admin_refund` asks Waxpeer for the `project_id` first (ADR-0007 Y; one
  `check-many-project-id`, 4 s, `skins.request_trade_client`, nothing locked) and only
  then locks and re-checks; a same-key twin that refunded meanwhile is answered with its
  stored page. Under the locks `buy_pending` goes off (no new attempt can start), then
  `orders.refund_to_balance` books it (`failed`, reason `admin`, actor `admin:<id>`). 409:
  `already_refunded`; `order_in_flight` (the skin may be on its way or delivered — a live or
  once-accepted trade at Waxpeer, a purchase on record — or the attention is unresolved or
  not a "nothing bought" case); `order_not_refundable` (unpaid, cancelled, delivered);
  `order_busy`; `waxpeer_unavailable` (the lookup failed or timed out; nothing booked).
- **Retry:** the same eligibility, minus the refund, and no purchase on record (`waxpeer_id`
  unset: a bought trade that stopped being reported is `ambiguous_trade` too, and a retry
  would buy it twice) — clears `attention_reason`,
  `buy_unconfirmed_at` and `resolved_*`, sets `buy_pending`, makes the order due now. The
  reconcile sweep's next `attempt_buy` looks the `project_id` up first: a purchase Waxpeer did
  make is adopted, never repeated. 409: `not_retryable`, `order_busy`.
- **The buy lease:** `order_busy` = a buy attempt may hold the order (`buy_pending` and
  `next_check_at` in the future: the lease, or a 403/429 backoff of ≤ 60 s). Try again once
  it lapses. While Waxpeer keeps answering 403, refund/retry of a `waxpeer_forbidden` order answer
  `order_busy` during each 60 s backoff: fix the IP whitelist first — the sweep then buys by
  itself.
- **Idempotency:** every write requires `Idempotency-Key` (16..160 chars). Order: lock the
  order, then its trade (ruling K) → replay lookup → the change → `audit.record` → replay
  row → commit. Scopes `admin.orders.resolve`, `admin.orders.refund`, `admin.orders.retry`;
  the replay row keeps `{request, response}` (request = `{number}` or `{number, note}`).
- **User card:** `orders` — the user's latest 20 orders as list rows.
- **Direction:** `admin` imports `orders`, `payments`, `fx` and `users` through their `api`;
  `orders` never imports `admin` (`tests/unit/test_import_order.py`).
- Tests: `tests/integration/test_admin_orders.py` (reads), `test_admin_orders_actions.py`
  (actions, the lease race, the flag/action pin), `test_admin_users.py` (card orders).

## Payments and audit (M3)

Read-only, `require_admin` on each router (401 / 403 as above), newest first with the shared
`core.cursor` keyset `(created_at DESC, id DESC)`; `limit` 1..100 (20); a bad cursor is 422
`cursor`.

| Route                                                                       | Answer               |
| --------------------------------------------------------------------------- | -------------------- |
| `GET /admin/payments?q=&status=&provider=&purpose=&cursor=&limit=`          | `AdminPaymentsOut`   |
| `GET /admin/payments/{id}`                                                  | `AdminPaymentDetail` |
| `GET /admin/audit?action=&target_type=&target_id=&actor_id=&cursor=&limit=` | `AuditOut`           |

- **Files:** `payments_routes.py`, `payments_service.py`, `payments_schemas.py`,
  `payments_kassa.py` (the three acquirers' rows), `audit_routes.py`, `audit_service.py`,
  `audit_schemas.py`.
- **Search:** `q` is upper-cased and matched as a prefix of `payments.number` (`%`, `_`
  literal), so `T7K` finds every attempt of that top-up. Filters combine with AND. One
  statement per page: the payer's name is a join.
- **Detail:** the attempt (`provider_ref`, scalar `metadata`), its top-up and the kassas'
  transactions for it (`kassa`, oldest first). Amount is soʻm for Click, **tiyin** for Payme
  and Uzum (`amount_unit`); `times` are UTC, an unset kassa time is `null`. Payme status is
  `created` / `performed` / `cancelled` / `cancelled_after_perform`.
- **`extra` is an allow-list** of strings: `account`; Click `service_id`, `click_paydoc_id`;
  Payme `reason`; Uzum `service_id`, `source` (`paymentSource`, cut at 32 characters) and
  `phone` masked to `+998••••••XX` (`mask_phone`: only the last two digits show). Nothing
  else of `payment_source` and no Payme fiscal data is returned.
- **Audit:** exact-match filters; a non-UUID `actor_id` is 422 `actor_id`. `payload` is the
  stored object as written by `record` (names of things, no PII).
- **Direction:** `admin` imports `click`, `payme`, `uzum` and `payments` through their `api`;
  none imports `admin.payments_*` / `admin.audit_*` (`tests/unit/test_import_order.py`).
- Tests: `tests/integration/test_admin_payments.py`, `test_admin_audit_routes.py`.
- Reading a payment when a customer says "paid, not credited": `docs/runbooks/click.md`,
  `payme.md`, `uzum.md`, section **Customer paid, balance not credited**.

## Public interface

`admin.api`: `require_admin` (dependency returning the `User`), `has_role`, `record` (audit).
`admin.deps.required_key` is the `Idempotency-Key` dependency of every admin write (users,
orders).
The routers are mounted from `api/v1/router.py` via `admin.routes`, `admin.users_routes`,
`admin.payments_routes`, `admin.audit_routes` and `admin.orders_routes`,
like `users`; the skins admin routes live in `skins.admin_routes`.
