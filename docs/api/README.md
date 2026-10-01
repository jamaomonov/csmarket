# API

`openapi.json` is generated — never hand-edit. Regenerate with `make gen-api`; CI's
`openapi-drift` job fails when the committed file differs from the app.

- Base path: `https://api.csmarket.uz/api/v1`. Probes: `/healthz` (liveness), `/readyz`
  (readiness: Postgres + Redis, 503 when either fails). `/metrics` is scraped on the
  internal network and answers 404 from the public host.
- Errors: RFC 7807 `application/problem+json` with `type` under `https://csmarket.uz/errors/`;
  429s carry `Retry-After`.
- Every state-changing endpoint accepts `Idempotency-Key` (≥ 16 chars) — spec §13.

## Auth (M1)

Steam OpenID is the only sign-in (ADR-0004). The flow, in short:

1. `GET /auth/steam/start?app=web|admin&locale=ru|uz|en` — 302 to Steam; Steam returns the
   browser to the **app's** `/auth/steam/callback`, not to the API.
2. `POST /auth/steam` `{app, params}` — the app forwards the `openid.*` params; the API
   verifies them with Steam and answers `{access_token, expires_in}` plus the cookie.
3. Every other call sends `Authorization: Bearer <access_token>`.

- **Access token:** EdDSA JWT, 15 minutes, in the JSON body. Keep it in memory; never in a
  cookie or `localStorage`. Roles are not in the token; the server reads them per request.
- **Refresh:** `POST /auth/refresh` with the `csmarket_refresh` cookie (`HttpOnly`,
  `SameSite=Lax`, 30 days, `.csmarket.uz` in prod). Rotates on every use; reusing an old
  cookie revokes every session of the user. Send requests with credentials (`include`).
- **Sign-out:** `POST /auth/logout` (204, idempotent) revokes the session and the Bearer.
- **Keyless writes.** `/auth/steam`, `/auth/refresh`, `/auth/logout` and
  `/me/trade-link/check` take no `Idempotency-Key`; each says why in its docstring.
  `PATCH /me` and `PUT /me/trade-link` take one.
- **`/auth/dev-login`** is not in this schema. It exists only when dev login is on and the
  environment is not prod; 404 otherwise.

### Errors

| Status | `type` suffix       | When                                                                                                                                                                                                   |
| ------ | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 401    | `unauthorized`      | No, invalid, expired or revoked token; failed Steam verification. Refresh once, then sign in                                                                                                           |
| 403    | `account-suspended` | The account is banned. **Do not refresh**; show the suspension notice                                                                                                                                  |
| 403    | `forbidden`         | Signed in, but not an admin (`/admin/*`)                                                                                                                                                               |
| 422    | `validation`        | Body errors. Trade-link failures add `code`: `trade_link_invalid` (not a Steam trade link), `trade_link_not_yours` (belongs to another Steam account), `trade_link_missing` (check with nothing saved) |
| 429    | `rate-limited`      | `ip_guard` or the coarse limiter; honour `Retry-After`                                                                                                                                                 |

### Me and trade link

- `GET /me` — the owner's profile, roles and trade link with its last verdict.
- `PATCH /me` `{locale?, email?}` — omitted = unchanged, `null` clears; a new email is
  unverified.
- `PUT /me/trade-link` `{url}` — saves without calling anyone; clears the previous verdict.
- `POST /me/trade-link/check` — advisory. `verdict` is `ok`, `warn` or `bad`, or `null`
  when the check was unavailable; `reason` is `invalid`, `private`, `trade_ban`, `hold` or
  `unavailable`. Cached 10 minutes; 4 s upstream timeouts.
