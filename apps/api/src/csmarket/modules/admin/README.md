# admin

The admin role gate and the admin audit trail. M1 shipped the gate and one probe,
`GET /api/v1/admin/me`; M2 adds `admin_audit_log` with the first admin actions (hiding a
catalogue item, editing search aliases — `skins/README.md`, **Admin catalogue**).

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
  `skins.alias.delete` (`skin_alias` / alias, `{"alias"}`).
- There is no audit UI or read endpoint yet; read it with `make psql`.
- Tests: `tests/integration/test_admin_audit.py`, `test_skins_admin_catalogue.py`.

## Public interface

`admin.api`: `require_admin` (dependency returning the `User`), `has_role`, `record` (audit).
The router is mounted from `api/v1/router.py` via `admin.routes`, like `users`; the skins admin
routes live in `skins.admin_routes`.
