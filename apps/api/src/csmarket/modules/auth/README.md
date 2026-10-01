# auth

Steam sign-in (OpenID 2.0, the only sign-in), sessions, access tokens, the Redis
`ip_guard`. Owns the `refresh_tokens` table; the account itself lives in `users`.

## Public interface

`auth.api` — other modules import nothing else from here:

| Name                  | What it is                                                                                  |
| --------------------- | ------------------------------------------------------------------------------------------- |
| `router`              | The `/api/v1/auth` routes (mounted in `api/v1/router.py`)                                   |
| `current_user`        | FastAPI dependency: the signed-in `User`; 401 absent/invalid, 403 banned                    |
| `SessionTokens`       | Access + refresh token pair and TTLs returned by the service                                |
| `TokensOut`           | Response body of every route that opens or rotates a session                                |
| `guard_ip`            | Two-axis Redis rate guard (`bucket`, optional `subject`); 429 past a limit                  |
| `trade_hold_days`     | Steam `GetTradeHoldDurations` for a trade link (used by `users`)                            |
| `revoke_all_sessions` | Sign a user out everywhere: revoke every live session, blocklist its `sid`s (admin ban, M3) |

## Tokens

| Token   | Lifetime | Where it lives                                                                 |
| ------- | -------- | ------------------------------------------------------------------------------ |
| Access  | 15 min   | EdDSA JWT in the JSON body; the app keeps it in memory and sends it as Bearer  |
| Refresh | 30 days  | Opaque, `csmarket_refresh` `HttpOnly` cookie; only its SHA-256 is in the table |

Refresh rotates on every use. One cookie serves the storefront and the admin (ruling P8).

Every revoked refresh row records why, in `revoked_reason`: `rotated` (a refresh),
`logout`, `admin` (`revoke_all_sessions`, the ban) or `reuse` (the trip-wire's
burn-down). NULL marks rows revoked before migration 0011 and reads as `rotated`. Presenting
a revoked refresh token again is answered in this order:

| Case                                      | Answer                        | Writes                                                     |
| ----------------------------------------- | ----------------------------- | ---------------------------------------------------------- |
| The owner is banned                       | `403 account-suspended`       | None                                                       |
| `rotated` or NULL: the token was replayed | `401` "reuse detected"        | The reuse trip-wire: every live session revoked as `reuse` |
| `logout`, `admin` or `reuse`              | `401` "refresh token revoked" | None                                                       |

The trip-wire is scoped to rotated tokens. A rotated token coming back means two holders
of one cookie, which is theft. A logged-out or ban-revoked cookie is only dead. Otherwise,
after an unban and a fresh sign-in, a stale cookie on another device would end the new
session.

`resolve_current_user` checks the ban **before** the blocklist. An admin ban (M3) also
revokes every session (`revoke_all_sessions`), and the apps must hear `403
account-suspended`, not `401` "session revoked" (which would send them refreshing). The
banned user's refresh is `403 account-suspended` as well, on every attempt and without a
write, so a suspended browser keeps its cookie and shows the suspension notice on each load
(`@csmarket/api-client` `isSuspended()`).

## Cookies

| Cookie             | Holds                           | Attributes                                                                    |
| ------------------ | ------------------------------- | ----------------------------------------------------------------------------- |
| `csmarket_refresh` | The opaque refresh token        | `HttpOnly`, `SameSite=Lax`, `Path=/`, 30 days; prod: `Secure`, `.csmarket.uz` |
| `csmarket_oid`     | A random sign-in nonce (no PII) | `HttpOnly`, `SameSite=Lax`, `Path=/api/v1/auth`, 10 min; same prod rules      |

`csmarket_oid` binds a Steam sign-in to the browser that started it (login-CSRF
defence): `/steam/start` mints `secrets.token_urlsafe(16)`, sets it as the cookie and
puts it into `return_to` as `n`. Steam signs `return_to`, so `POST /steam` accepts an
assertion only when its signed `n` equals the cookie (constant-time compare). The nonce
is single-use: the completion clears the cookie on every outcome. Without it an attacker
could hand a victim their own Steam redirect and sign the victim into the attacker's
account.

## Table

`refresh_tokens` — `id` (the `sid` claim of the access tokens minted from it),
`user_id`, `token_hash`, `expires_at`, `revoked_at`, `revoked_reason`, `created_at`.
`revoked_reason` (migration `0011_refresh_revoked_reason`, CHECK
`ck_refresh_tokens_revoked_reason`) is `rotated`, `logout`, `admin` (a ban) or `reuse` (the
trip-wire's burn-down); `NULL` on a live row, and on a legacy revoked row it counts as
`rotated`. Only a `rotated` token trips the reuse wire (above). Revoked or expired rows are
kept 7 days, then purged by `purge_stale_refresh_tokens`.

## HTTP surface

| Route                                                             | Does                                                                                                |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `GET /api/v1/auth/steam/start?app=web\|admin&locale=…`            | 302 to Steam; `return_to` = the app's callback `?locale=…&n=<nonce>`; sets `csmarket_oid`           |
| `POST /api/v1/auth/steam` `{app, params}`                         | Checks the nonce, verifies with Steam, upserts the user, sets the cookie; clears `csmarket_oid`     |
| `POST /api/v1/auth/refresh`                                       | Rotates the cookie, returns a fresh access token                                                    |
| `POST /api/v1/auth/logout`                                        | Revokes the session (and the Bearer's `jti`), clears the cookie; 204                                |
| `POST /api/v1/auth/dev-login` `{steam_id, display_name?, admin?}` | Dev/e2e only: 404 (before the body is read) unless `dev_login_enabled` and not prod; not in OpenAPI |

Refused with 401 and nothing written, all but the last before any call to Steam: a
`claimed_id` that is not `https://steamcommunity.com/openid/id/<digits>`; an
`openid.signed` that leaves out any of `claimed_id`, `identity`, `return_to`,
`response_nonce`, `assoc_handle`; a `return_to` whose scheme, host and path are not
exactly this app's callback; a missing `csmarket_oid` cookie or a signed `n` that does not
match it; Steam answering anything but `is_valid:true`. A banned account → 403
`account-suspended` at sign-in and on its next request.

Access tokens must carry `sid` (with `iat`, `exp`, `iss`, `sub`, `jti`); one without it
is refused, since it could not be revoked with its session.

## Redis keys

| Key                                           | Meaning                                             |
| --------------------------------------------- | --------------------------------------------------- |
| `auth:revoked:{jti}`                          | A logged-out access token; TTL = its remaining life |
| `auth:revoked_sid:{sid}`                      | A revoked session's access tokens; TTL = access TTL |
| `auth:ipguard:{bucket}:{hash(ip)}`            | Per-address counter; the IP is hashed, never raw    |
| `auth:ipguard:{bucket}:{hash(ip)}:s:{digest}` | Per-(address, subject) counter                      |

Blocklist reads **and writes** and the guard fail open on a Redis error: the
`refresh_tokens` row is the source of truth and is written regardless, so a Redis blip
costs only the acceleration (an access token lives out its 15 minutes) — never a 500 on
refresh or logout. Failures log `auth.blocklist_unreadable` / `auth.blocklist_unwritable`
with the blocklist kind only, never the key. The guard counts with `INCR` +
`EXPIRE … NX` in one `MULTI`, so no counter is ever left without a TTL.

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
rejections log only a fixed reason and, for a transport failure, the exception's class
name (`auth.steam.rejected reason=… error=ConnectTimeout`) — never httpx's message, which
can carry URLs and request data. See `docs/security/pii-handling.md`.
