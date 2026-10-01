# auth

Steam sign-in (OpenID 2.0, the only sign-in), sessions, access tokens, the Redis
`ip_guard`. Owns the `refresh_tokens` table; the account itself lives in `users`.

## Public interface

`auth.api` — other modules import nothing else from here:

| Name              | What it is                                                                 |
| ----------------- | -------------------------------------------------------------------------- |
| `router`          | The `/api/v1/auth` routes (mounted in `api/v1/router.py`)                  |
| `current_user`    | FastAPI dependency: the signed-in `User`; 401 absent/invalid, 403 banned   |
| `SessionTokens`   | Access + refresh token pair and TTLs returned by the service               |
| `TokensOut`       | Response body of every route that opens or rotates a session               |
| `guard_ip`        | Two-axis Redis rate guard (`bucket`, optional `subject`); 429 past a limit |
| `trade_hold_days` | Steam `GetTradeHoldDurations` for a trade link (used by `users`)           |

## Tokens

| Token   | Lifetime | Where it lives                                                                 |
| ------- | -------- | ------------------------------------------------------------------------------ |
| Access  | 15 min   | EdDSA JWT in the JSON body; the app keeps it in memory and sends it as Bearer  |
| Refresh | 30 days  | Opaque, `csmarket_refresh` `HttpOnly` cookie; only its SHA-256 is in the table |

Refresh rotates on every use. Presenting a refresh token that was already rotated
revokes every session of the user (the reuse trip-wire). One cookie serves the storefront
and the admin (ruling P8).

## Table

`refresh_tokens` — `id` (the `sid` claim of the access tokens minted from it),
`user_id`, `token_hash`, `expires_at`, `revoked_at`, `created_at`. Revoked or expired rows
are kept 7 days, then purged by `purge_stale_refresh_tokens`.

## HTTP surface

| Route                                                             | Does                                                                      |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `GET /api/v1/auth/steam/start?app=web\|admin&locale=…`            | 302 to Steam; `return_to` = the app's own `/auth/steam/callback`          |
| `POST /api/v1/auth/steam` `{app, params}`                         | Verifies the `openid.*` params with Steam, upserts the user, sets cookie  |
| `POST /api/v1/auth/refresh`                                       | Rotates the cookie, returns a fresh access token                          |
| `POST /api/v1/auth/logout`                                        | Revokes the session (and the Bearer's `jti`), clears the cookie; 204      |
| `POST /api/v1/auth/dev-login` `{steam_id, display_name?, admin?}` | Dev/e2e only: 404 unless `dev_login_enabled` and not prod; not in OpenAPI |

A `return_to` minted for another origin, a `claimed_id` that is not
`https://steamcommunity.com/openid/id/<digits>`, or Steam answering `is_valid:false` → 401
and nothing written. A banned account → 403 `account-suspended` at sign-in and on its next
request.

## Redis keys

| Key                                           | Meaning                                             |
| --------------------------------------------- | --------------------------------------------------- |
| `auth:revoked:{jti}`                          | A logged-out access token; TTL = its remaining life |
| `auth:revoked_sid:{sid}`                      | A revoked session's access tokens; TTL = access TTL |
| `auth:ipguard:{bucket}:{hash(ip)}`            | Per-address counter; the IP is hashed, never raw    |
| `auth:ipguard:{bucket}:{hash(ip)}:s:{digest}` | Per-(address, subject) counter                      |

Blocklist reads and the guard fail open on a Redis error.

## External calls

| Call                                 | Timeout | On failure                             |
| ------------------------------------ | ------- | -------------------------------------- |
| Steam OpenID `check_authentication`  | 10 s    | 401 — it _is_ the authentication       |
| Steam `GetPlayerSummaries` (persona) | 5 s     | Best-effort: sign-in proceeds nameless |
| Steam `GetTradeHoldDurations`        | 4 s     | Raises; the caller decides (advisory)  |

The persona and trade-hold calls need `CSMARKET_STEAM_API_KEY` and are counted in
`csmarket_steam_web_api_calls_total`.

## PII

Never log the steamid, the `openid.*` params, an IP, a token or a trade link. Steam
rejections log only a reason (`auth.steam.rejected`). See `docs/security/pii-handling.md`.
