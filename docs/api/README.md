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

1. `GET /auth/steam/start?app=web|admin&locale=ru|uz|en` — a top-level navigation, not
   an XHR. 302 to Steam and sets the `csmarket_oid` sign-in nonce cookie (`HttpOnly`, 10
   min); Steam returns the browser to the **app's** `/auth/steam/callback?locale=…&n=…`,
   not to the API.
2. `POST /auth/steam` `{app, params}` — the app forwards only the `openid.*` params, with
   credentials (`include`) so the nonce cookie goes along. The API requires the signed
   `return_to` to carry the cookie's nonce (else 401, nothing written), verifies with Steam
   and answers `{access_token, expires_in}` plus the cookie. The nonce is single-use: a
   failed attempt restarts from step 1.
3. Every other call sends `Authorization: Bearer <access_token>`.

- **Access token:** EdDSA JWT, 15 minutes, in the JSON body. Keep it in memory; never in a
  cookie or `localStorage`. Roles are not in the token; the server reads them per request.
- **Refresh:** `POST /auth/refresh` with the `csmarket_refresh` cookie (`HttpOnly`,
  `SameSite=Lax`, 30 days, `.csmarket.uz` in prod). Rotates on every use; reusing an old
  cookie revokes every session of the user. Send requests with credentials (`include`).
- **A failed refresh:** only `401` / `403` mean the session is over. A `5xx`, `429` or a
  network error is transient: keep the hint and do not call logout.
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
- `PUT /me/trade-link` `{url}` — saves without calling anyone. A different link clears the
  previous verdict, reason and `checked_at`; re-saving the same link keeps them.
- `POST /me/trade-link/check` — advisory. `verdict` is `ok`, `warn` or `bad`, or `null`
  when the check was unavailable; `reason` is `invalid`, `private`, `trade_ban`, `hold` or
  `unavailable`. Cached 10 minutes; 4 s upstream timeouts.

### Skins catalogue (M2)

Public, no sign-in. Under `/skins`:

- `GET /skins/catalog` — filters `category`, `weapon`, `exterior`, `stattrak`, `souvenir`,
  `rarity`, `team`, `min_uzs`, `max_uzs`, `q`; `sort` (`price`, `-price` default, `discount`,
  `popular`); `limit` 1..100 (48); `cursor`. The cursor is **opaque**: pass back `next_cursor`
  as given. A malformed cursor is 422.
- `GET /skins/facets?category=` — counts for the filters; an unknown category is 422.
- `GET /skins/suggest?q=` — search-box suggestions.
- `GET /skins/{slug}` — one item with its wears and cheapest offers; 404 for an unknown or
  hidden slug.
- `GET /skins/{slug}/listings` — live offers `{items, degraded}`. `degraded: true` means the
  answer is the last cached or last snapshot offers because Waxpeer could not answer; it is
  not an error. Rate-limited per IP in its own bucket (`skins-listings`); 429 carries
  `Retry-After`. Offers carry a numeric `listing_id` (opaque; M4 checkout will need it).
- `GET /skins/seo/slugs?offset&limit` (≤ 5 000) — slugs for the sitemap.

Conventions: **money is a string** (`price_usd` with 2 decimals, `price_uzs` whole soʻm
rounded up to 100). **`price_uzs` is `null` without a fresh CBU rate** (clients show dollars
and soʻm filters are ignored). Hidden items and categories outside
`CSMARKET_SKINS_CATEGORIES` never appear. Nothing in a response names Waxpeer. These are `GET`s:
no `Idempotency-Key`. Bodies of the catalogue, facets and suggest are cached 60 s.

### Admin catalogue (M2)

All under `/admin/skins`, admin only (401 without a token, 403 for a customer).

- `GET /admin/skins/catalog/status` — counts, newest price tick, last import / price-sync run,
  the CBU rate, `sync_enabled`, `waxpeer_key_set`.
- `GET /admin/skins/items?q=&hidden=&limit=` — find items, hidden ones included.
- `PATCH /admin/skins/items/{slug}` `{hidden}` — hide or show an item everywhere public.
- `GET /admin/skins/aliases`, `PUT /admin/skins/aliases/{alias}` `{text}`,
  `DELETE /admin/skins/aliases/{alias}` (204) — search aliases; alias 1..64 letters, digits,
  spaces or hyphens, text 1..128, both stored lower-case.
- `PATCH`, `PUT` and `DELETE` take an `Idempotency-Key` (≥ 16 chars, optional here): a repeat replays the first response
  and writes nothing, including no second audit row. Every write is audited in
  `admin_audit_log`.
