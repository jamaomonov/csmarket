# admin

The admin role gate, the admin audit trail and the admin users API. M1 shipped the gate and
one probe, `GET /api/v1/admin/me`; M2 adds `admin_audit_log` with the first admin actions
(hiding a catalogue item, editing search aliases — `skins/README.md`, **Admin catalogue**);
M3 adds the users list and card, ban/unban and the audited balance adjustment.

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
  literal) or an exact 17-digit Steam ID. The balance is a correlated subquery
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

## Public interface

`admin.api`: `require_admin` (dependency returning the `User`), `has_role`, `record` (audit).
The routers are mounted from `api/v1/router.py` via `admin.routes` and `admin.users_routes`,
like `users`; the skins admin routes live in `skins.admin_routes`.
