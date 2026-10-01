# 0004. Steam sign-in, sessions and the admin gate

- **Status**: Accepted
- **Date**: 2026-10-01
- **Deciders**: @jamaomonov
- **Tags**: security | backend | frontend

## Context and problem statement

Steam OpenID 2.0 is the only door into csmarket (spec §7.1): no email, no password, no
Google, no Telegram. The same sign-in serves the storefront (`csmarket.uz`) and the admin
(`admin.csmarket.uz`); an admin is a normal Steam account with the `admin` role.

The spec sketches the flow at a high level: the callback on the API and "cookies (access,
refresh)". M1 had to fix the details: where Steam returns the browser, where the access
token lives, how the web and admin share a session, how a developer signs in without Steam,
and what happens to keys and the admin role outside prod.

## Decision drivers

- A forged or replayed Steam callback must never open a session.
- Steam shows the realm to the user: it must be the site they know, not `api.csmarket.uz`.
- An XSS must not be able to read a 30-day session.
- Local work and e2e must run without Steam and without secrets.
- The same person is the same identity in web and admin.

## Considered options

1. **Callback on the API** (`GET /auth/steam/callback`, as the spec says) with access and
   refresh both in cookies.
2. **Callback on the app, refresh cookie + in-memory access token** — the YuPay shape.

## Decision outcome

**Chosen option:** 2. Rulings P1, P2, P6, P7, P8 of the M1 plan.

- **P1 — The callback lands on the app.** `GET /api/v1/auth/steam/start?app=web|admin`
  302s to Steam with `return_to = <app origin>/auth/steam/callback` and the app origin as
  realm; both come from settings, never from the query. The app's callback page `POST`s the
  `openid.*` params to `/api/v1/auth/steam`, which checks `return_to`, the `claimed_id`
  shape and Steam's `check_authentication`, then upserts the user and sets the cookie. The
  callback page strips the params from the URL at once.
- **P2 — The access token is not a cookie.** The refresh token is an opaque `HttpOnly`
  cookie (`csmarket_refresh`, 30 days, rotating, only its SHA-256 stored). The EdDSA access
  JWT (15 min) comes in the JSON body, lives in JS memory and is re-minted from the cookie
  on page load. Bearer needs no CSRF token on writes, and an XSS cannot lift the long-lived
  credential.
- **P6 — Dev login.** `POST /auth/dev-login` exists only when
  `CSMARKET_DEV_LOGIN_ENABLED=true` **and** `environment != prod`; otherwise 404. It is
  hidden from OpenAPI. It drives local work and the e2e suite.
- **P7 — Ephemeral JWT keys outside prod.** Empty `CSMARKET_JWT_*_KEY` and
  `environment != prod`: the API generates an in-process Ed25519 pair. Prod refuses to mint
  and `missing_prod_settings` names the keys.
- **P8 — One session for web and admin.** In prod the cookie is scoped to `.csmarket.uz`;
  on localhost it is host-only. Signing out of one signs out of the other.

Related decisions taken while building M1:

- v1 routers mount in `apps/api/src/csmarket/api/v1/router.py`, collecting each module's
  `routes.py`. Mounting from a package `__init__` closed an import cycle (`auth` imports
  `users.api`); `tests/unit/test_import_order.py` guards it.
- Refresh-token reuse detection commits the revocation of every session **before** raising
  `401`, so the request-scoped `get_session` rollback cannot undo it.
- A Waxpeer `200` whose body is not a JSON object counts as "unavailable", never as a
  reason: an unreadable answer is an outage, and the link stays saved with verdict `null`.
- The storefront skips the boot refresh on the Steam return URL (decided by `openid.mode`
  in the query), so the callback page and the boot refresh do not race.
- The shared browser session client (memory token, single-flight refresh, `onAuthLost`)
  lives in `@csmarket/api-client` as `createSessionClient`; web and admin both use it.

### New dependencies (AGENTS §4)

| Dependency                            | Where                 | Why                                                                                 |
| ------------------------------------- | --------------------- | ----------------------------------------------------------------------------------- |
| `pyjwt[crypto]>=2.10` (2.15.1 locked) | `apps/api`            | EdDSA access tokens; the `crypto` extra brings `cryptography` for Ed25519           |
| `email-validator>=2.2` (2.3.0)        | `apps/api`            | `EmailStr` on `PATCH /me`; pulls `dnspython` (2.8.0), unused for lookups            |
| `@tanstack/react-query` `^5.59.20`    | `apps/web`            | Account page queries and mutations; the admin already had it                        |
| `jsdom` `^25.0.1` (dev)               | `packages/api-client` | Vitest environment for the session client (it reads `localStorage` and `navigator`) |

### Positive consequences

- Steam and the user see one site name; the API is never a Steam realm.
- A stolen page script cannot read the refresh token; writes need no CSRF tokens.
- One identity and one sign-out across web and admin.
- Local development and e2e need no Steam and no keys.

### Negative consequences

- A cookie scoped to `.csmarket.uz` is sent to every `*.csmarket.uz` host. Only `api`
  reads it; no other subdomain may run untrusted code.
- In dev, access tokens die when the API restarts (new ephemeral key); the refresh cookie
  survives, so the app re-mints on the next load.
- Dev login is a hole by design. It must stay prod-off: `test_prod_never_exposes_dev_login`
  fails the build if `environment=prod` ever exposes it, and `infra/secrets-example/api.env`
  sets the flag to `false`.
- The spec's "callback on the API" wording is superseded for M1; spec §7.1 stays as written.

## Validation

- `test_auth_steam.py`: foreign `return_to`, a non-Steam `claimed_id` and `is_valid:false`
  all give 401 and no user row.
- `test_auth_refresh.py`: reuse burns every session; two concurrent refreshes with one
  token cannot both win.
- `test_dev_login.py::test_prod_never_exposes_dev_login`.
- The e2e suite signs in through dev login and opens the admin gate.

## Alternatives considered (detail)

### Callback on the API, both tokens in cookies

Matches the spec text. But Steam would show `api.csmarket.uz` as the realm, the cookie
would be set by a top-level redirect the app does not control, and an access-token cookie
needs CSRF protection on every write.

## References

- Spec §3.2 `auth`, §5, §7.1, §7.2, §13.
- [ADR-0003](./0003-own-caddy-behind-cloudflare.md) — client IP for `ip_guard`.
- `docs/architecture/sequence-diagrams/steam-sign-in.mmd`, `docs/architecture/cache-keys.md`.
