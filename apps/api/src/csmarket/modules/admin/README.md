# admin

The admin role gate. M1 ships the gate and one probe, `GET /api/v1/admin/me`; admin
actions and the `admin_audit_log` arrive with the first admin action (M3).

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

## Public interface

`admin.api`: `require_admin` (dependency returning the `User`), `has_role`. The router is
mounted from `api/v1/router.py` via `admin.routes`, like `users`.
