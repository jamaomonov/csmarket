# PII handling

The owner's rule, verbatim in substance: **never log PII — Steam ID, email, IP, trade-link
token.** Order numbers and amounts are fine. This file lists what personal data csmarket
holds, where it may appear, and where it never may. Update it with any change that adds a
field, a log line, a metric or a third party that sees one of these values (`AGENTS.md` § 5).

## Inventory

| Data                     | Stored in                                                  | Arrives in | Notes                                                                                                                                                                                                                 |
| ------------------------ | ---------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Steam ID (SteamID64)     | `users.steam_id`                                           | M1         | The identity. Public on Steam, still personal here: it links a person to purchases. Never logged (redactor key `steam_id` and stem `*steamid*`)                                                                       |
| Display name, avatar URL | `users.display_name`, `users.avatar_url`                   | M1         | Copied from Steam at sign-in                                                                                                                                                                                          |
| Email                    | `users.email` (optional)                                   | M1         | Only for receipts and order emails (M4). Unverified until then (`email_verified_at` is null). Never logged                                                                                                            |
| Trade link               | `users.trade_link`; a snapshot in `orders.trade_link` (M4) | M1         | Its `token` is a **credential**: anyone holding it can send that account offers. `partner` is the account id. Returned only to its owner (`GET /me`); never logged                                                    |
| Client IP                | **not stored** in Postgres                                 | M0         | Rate-limit counters only (below)                                                                                                                                                                                      |
| Payer phone, card type   | `uzum_transactions.payment_source` (jsonb)                 | M3         | What Uzum's `/confirm` sends besides the envelope (`phone`, `cardType`, `paymentSource`, …). Stored for reconciliation; never logged (redactor key `payment_source`, stem `*phone*`); admin shows it masked (Task 10) |

### Client IP

- The coarse limiter (slowapi, M0) keeps per-IP, per-route counters **in the API process's
  memory** for its window (one minute by default). Nothing is written to disk.
- `ip_guard` (M1) keeps per-IP counters in **Redis** under keys that expire with their window
  (60 s by default). Never in Postgres, never in a column.
- The trade-link verdict cache (M1) is keyed by a **hash** of the link, never the link; its
  value is the verdict and reason only.
- In `ip_guard` keys the address appears only as `hash_short(ip)` (12 hex characters), and a
  subject (the user id) as a SHA-256 prefix. Keys live one window (60 s). Catalogue:
  `docs/architecture/cache-keys.md`.

### Sign-in and trade-link specifics (M1)

- **OpenID callback params.** Steam returns the browser to the app with `openid.*` in the
  query string (it includes the claimed Steam ID). The callback page `POST`s them to the API
  and replaces the URL at once, so they do not stay in the address bar or history. The API
  never logs them; a rejected sign-in logs a fixed reason and, for a transport failure, the
  exception class name only (`auth.steam.rejected`).
- **Sign-in nonce cookie.** `csmarket_oid` holds a random nonce (no PII) for 10 minutes
  between `/auth/steam/start` and the completion, which clears it; the same nonce rides
  Steam's `return_to` as `n`. It identifies nobody and is never logged.
- **Upstream error text is never logged.** `httpx` exceptions carry the request URL: Steam
  Web API calls carry `key=` and the trade token, Waxpeer's key rides the query string. Only
  the exception **type name** is logged, and the `httpx` / `httpcore` loggers are capped at
  WARNING (`core/logging.py`).
- **Refresh token.** Only its SHA-256 is stored (`refresh_tokens.token_hash`); the raw value
  lives in an `HttpOnly` cookie. The access JWT carries no PII beyond the user id.
- **Roles** are in `users.roles`. `grant_admin` prints one word and never the Steam ID.
- **Admin audit log** (`admin_audit_log`, M2): the actor is `actor_user_id` (our uuid); the
  `payload` names things only (slugs, aliases) — never a Steam ID, email or IP. M3 adds
  `users.ban` / `users.unban` / `wallet.adjust` with the operator's `reason` (and the signed
  amount); the target is the user's uuid in `target_id`, never a Steam ID.
- **Admin users API (M3):** the card shows an operator the Steam ID, email and trade-link
  verdict; the trade link only masked (`partner` kept, token `••••` + last 2 characters —
  `users.mask_trade_link`), never whole. An admin adjustment's reason lives in
  `wallet_transactions.metadata` and reaches admin views only (`entries_for_admin`); the
  customer's `/wallet/entries` never carries `actor` or `metadata`. Nothing here is logged
  with a user id (`wallet.posted` carries kind, transaction id and amount only).
- **Catalogue and rate (M2) hold no personal data.** The catalogue, price sync and listings
  carry items and prices only; CBU calls carry nothing about a person. Waxpeer's API key rides
  the query string, so a Waxpeer URL and `httpx` exception text are never logged: only the
  method, path, status and the exception type name (`skins.prices.failed error=…`). The listings
  route's `ip_guard` bucket keys on `hash_short(ip)` like the others; cached listings and
  catalogue pages are public data.

## Where each may appear

| Channel                | Rule                                                                                                                                                                                                                                                                                        |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Application logs       | **Never.** `core/logging.py` redacts by key (`steam_id`, `email`, `ip`, `trade_link`, `partner`, `token`, `user_id`, …) and by stem (`*email*`, `*steamid*`, `*_ip`, `*_token`). Use `hash_short()` when a log needs to correlate one person's events                                       |
| Prometheus metrics     | **Never as a label.** Labels are bounded `Literal`s (`core/metrics.py`, rule 1)                                                                                                                                                                                                             |
| Sentry                 | `send_default_pii=False` (no bodies, headers, cookies, user) and `include_local_variables=False` (no stack-frame locals) — `core/observability.py`                                                                                                                                          |
| Traces, locals in logs | Off: structlog renders tracebacks with `show_locals=False`                                                                                                                                                                                                                                  |
| URLs and query strings | Never carry a trade link or token. Advisory lookups that take one are `POST`. Our own logs drop query strings (below), but Cloudflare and browsers still see full URLs                                                                                                                      |
| Edge and access logs   | Caddy's access log and its error log pass a filter (`(pii_filter)` in `infra/caddy/Caddyfile.prod`): it keeps method, host, path, status, size and duration and deletes the client address, every request and response header and the query string. uvicorn runs with `--no-access-log`     |
| Chat, docs, tests      | Never a real trade-link token or a real person's Steam ID; use redrawn / fake values                                                                                                                                                                                                        |
| Admin UI               | Shows what an operator needs to resolve an order (M1+); every admin action is audited in `admin_audit_log`                                                                                                                                                                                  |
| Third parties          | Steam (Web API) receives the Steam ID and the trade token for the hold check, and its OpenID service sees the sign-in (M1); Waxpeer receives the trade link to check it (M1) and its `partner` and `token` to deliver (M4); acquirers receive the order number and amount, not the Steam ID |

## Retention

Retention for `users` (deletion via `deleted_at`), orders, and backups is decided with the
modules that own them: M1 for accounts, M4 for orders and trades, M5 for backups.
