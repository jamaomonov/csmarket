# PII handling

The owner's rule, verbatim in substance: **never log PII — Steam ID, email, IP, trade-link
token.** Order numbers and amounts are fine. This file lists what personal data csmarket
holds, where it may appear, and where it never may. Update it with any change that adds a
field, a log line, a metric or a third party that sees one of these values (`AGENTS.md` § 5).

## Inventory

| Data                               | Stored in                                                                 | Arrives in | Notes                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Steam ID (SteamID64)               | `users.steam_id`                                                          | M1         | The identity. Public on Steam, still personal here: it links a person to purchases. Never logged (redactor key `steam_id` and stem `*steamid*`)                                                                                                                                                                                                                                                                                     |
| Display name, avatar URL           | `users.display_name`, `users.avatar_url`                                  | M1         | Copied from Steam at sign-in                                                                                                                                                                                                                                                                                                                                                                                                        |
| Email                              | `users.email` (optional); `email_outbox.address` (a `verify` letter only) | M1, M4b    | Order letters go only to a verified address (`email_verified_at`, set by the confirmation link). Resolved at send time; order letters store no address. Sent to Resend (the processor) with the letter. Never logged                                                                                                                                                                                                                |
| Trade link                         | `users.trade_link`; a snapshot in `orders.trade_link` (M4a)               | M1         | Its `token` is a **credential**: anyone holding it can send that account offers. `partner` is the account id. Returned only to its owner (`GET /me`); never logged                                                                                                                                                                                                                                                                  |
| API key (ADR-0017)                 | `api_keys.token_hash`, `api_keys.ip_allowlist`                            | plan B     | Only the SHA-256 of the `csm_…` token is stored; the token is shown once and never logged (the redactor masks values starting `csm_` and the `authorization` header; logs carry the key's uuid only). The optional allow-list holds the customer's own server addresses. Revoked keys are kept (`orders.api_key_id` is RESTRICT)                                                                                                    |
| Buyer trade links of third parties | `orders.trade_link` of an API order                                       | plan B     | An API client sends **its own buyer's** trade link with every purchase, so the account may hold many other people's links (`partner` + `token` credentials). Same rules as any order link: validated for form only, passed to the supplier, never logged, masked in the admin, and erased with the **30-day** job below (`orders.erase_trade_links`, `channel` makes no difference). The public order read does not return the link |
| Client IP                          | **not stored** in Postgres                                                | M0         | Rate-limit counters only (below)                                                                                                                                                                                                                                                                                                                                                                                                    |
| Trade seller (public)              | `skin_trades.seller` (jsonb)                                              | M4a        | The Waxpeer seller's public Steam profile: name, avatar URL, Steam level, account age. Shown to the buyer on the order page and to admins. Never the seller's Steam ID (not stored; `seller_steam_id` is on the redaction list)                                                                                                                                                                                                     |
| Payer phone, card type             | `uzum_transactions.payment_source` (jsonb)                                | M3         | What Uzum's `/confirm` sends besides the envelope (`phone`, `cardType`, `paymentSource`, …). Stored for reconciliation; never logged (redactor key `payment_source`, stem `*phone*`); admin shows only the source label and the phone masked (`+998••••••67`, `admin.payments_kassa.mask_phone`)                                                                                                                                    |

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
- The public API's failed-authentication counter `public_api:authfail:{hash_short(ip)}` (60 s)
  follows the same rule. A key's optional IP allow-list is the customer's own server addresses,
  set by an admin.

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
- **Profile page (storefront, 2026-10-06):** «Профиль» shows the signed-in owner their own
  Steam ID (with a copy button and a link to their Steam profile), name, avatar and join date,
  all from `GET /me`, which already returned them to the owner. Nothing about another person,
  nothing new leaves the API.
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
- **Admin payments API (M3):** the payment page shows the payer's display name and our ids. A
  kassa's row reaches the operator through an allow-list (`account`, `service_id`,
  `click_paydoc_id`, Payme `reason`, Uzum `source` and a masked `phone`); `payment_source`
  is never passed through whole, Payme fiscal receipts are not shown, and the audit-log read
  returns payloads exactly as `audit.record` stored them (names of things, no PII).
- **Money (M3).** Ledger, top-up and kassa log lines carry the top-up number and the amount,
  never a user id (`wallet.posted`, `payments.topup.*`, `click.callback`, `payme.rpc`,
  `uzum.callback`): logs never tie a person to money. Kassa secrets never reach a log — the
  Click secret and `sign_string`, Payme keys, Uzum passwords and every `Authorization` header
  (redacted by key and stem; Caddy's `pii_filter` drops all request headers). Uzum's
  `payment_source` (the payer's phone) is stored only in `uzum_transactions`, never logged, and
  leaves the API only masked in admin. The customer's `/wallet/entries` carries no actor and no
  reason; an admin's adjustment reason is operator text visible to admins only (card and audit
  log), and the runbook asks for no personal data in it (`docs/runbooks/wallet.md`). The
  admin card shows the trade link masked. Metric `csmarket_kassa_rejections_total` is labelled
  by kassa and reason only.
- **Admin orders API (M4a):** the order page shows the order's trade-link snapshot only
  masked (`trade_link_masked`, `users.mask_trade_link`), never `orders.trade_link`; the list
  rows carry no link at all. The order actions' audit payloads are an attention reason or an
  amount (`orders.trade.resolve` `{reason}`, `orders.buy.retry` `{reason}`, `orders.refund`
  `{amount_uzs}`), target the order number; the operator's resolve note lives only in
  `skin_trades.resolved_note` (admin views only; operator text, no personal data in it).
- **Orders and trades (M4a).** `orders.trade_link` is a snapshot of the buyer's link taken at
  checkout, so a later link change cannot redirect a paid order. It is stored, sent only to
  Waxpeer (as `partner` and `token` on `buy-one-p2p`, a query string, so a Waxpeer URL is
  never logged), never logged, never in a customer answer (`OrderOut` carries no link) and
  shown to admins only masked. Waxpeer's lookup answers carry the buyer's `for_steamid64`:
  `skins.waxpeer_trades.parse_trade` drops it, so it is never stored, and it is on the log
  redaction list anyway. Order, buy, trade and refund log lines (`orders.created`,
  `orders.paid`, `orders.buy`, `orders.refunded`, `orders.trade.*`) carry the order number,
  amounts and outcome codes, never a user id; `orders.buy.crashed` carries the order uuid and
  the error type. Waxpeer error text and bodies are never logged (they can echo the link). The
  dev Waxpeer fake keeps no link and no Steam ID in Redis. Metrics are labelled by outcome or
  reason only.
- **Skinslink, the second buy source (ADR-0010).** The buyer's trade link goes to Skinslink
  only as `partner` + `token` in the JSON body of `POST /merchant/purchase` — never in a URL,
  never logged; the API key rides the `X-Api-Key` header. `skinslink_api_key` and
  `skinslink_secret` are on the log redaction list. Skinslink's purchase answers and webhooks
  can carry the buyer's `steam_id`: `skinslink.client` keeps only the purchase id, our
  `merchant_tx_id`, the status, Steam's trade offer id, the fail reason, the amount, the asset
  id and the hold end, so **no Steam ID is stored** (and `steam_id` is redacted anyway).
  `skinslink_purchases` holds no personal data; the mirror (`skinslink_items`) holds items
  and prices only. Skinslink's error bodies are never logged (they can echo the request,
  token included): log lines carry the endpoint, the status and the refusal code. The webhook
  logs only its kind; buy and status lines carry the order number and the outcome. Metrics are
  labelled by endpoint and outcome only.
- **LIS-SKINS, the third buy source (ADR-0012).** The buyer's trade link goes to LIS-SKINS
  only as `partner` + `token` in the JSON body of `POST /market/buy` — never in a URL, never
  logged; the API key rides an `Authorization: Bearer` header. `lisskins_api_key` and
  `authorization` are on the log redaction list. LIS-SKINS' purchase answers (`market/buy`,
  `market/info`) carry the buyer's `steam_id`: `lisskins.client` never reads it, so **no Steam
  ID is stored**. `lisskins_purchases` keeps our `custom_id`, the lot, the purchase id, the
  status, the return reason and error code, Steam's trade offer id and expiry, and the
  amount — no personal data. The public price export (`lisskins_offers`, `lisskins_state`)
  holds lots and prices only. Error bodies are never logged: refusals log the endpoint, the
  status and the code; buy and status lines carry the order number and the outcome. Metrics
  are labelled by endpoint and outcome only.
- **Catalogue and rate (M2) hold no personal data.** The catalogue, price sync and listings
  carry items and prices only; CBU calls carry nothing about a person. Waxpeer's API key rides
  the query string, so a Waxpeer URL and `httpx` exception text are never logged: only the
  method, path, status and the exception type name (`skins.prices.failed error=…`). The listings
  route's `ip_guard` bucket keys on `hash_short(ip)` like the others; cached listings and
  catalogue pages are public data.

- **Email confirmation (M4b):** the link carries an opaque token — `user_id | email | expiry`
  sealed with SecretBox under the `csmarket:email-verify:v1` key (`users.email_verify`), so a
  URL logged by a browser or Cloudflare reveals neither the address nor the account. The
  token sits in the `verify` outbox row's payload until sent; it is never logged. Letters
  never carry a trade link, a Steam ID or the balance. The dev transport files letters in
  Redis by user id, without the address.
- **Email outbox (M4b):** order letters' rows hold no address (the recipient is resolved
  when sent); a `verify` row snapshots the address it confirms, and the nightly erase job
  (`orders.erase_trade_links`) nulls it 7 days after it was queued. Resend, as a processor,
  receives the recipient address, the subject and the body of each letter it sends.

### Payout cards (ADR-0016)

- **Card number** — `payout_cards.number_enc` + `number_nonce`: encrypted with `core.crypto`
  under the purpose `csmarket:payout-card:v1` (a stolen dump alone yields nothing). In the
  clear: `last4` and the type. The full number is returned only by
  `POST /admin/sales/payouts/{id}/reveal`, to an admin, audited every time
  (`sales.card.show` / `sales.card.copy`, payload `last4`), and is never stored as an
  idempotency replay, never in a letter, a log (`card_number`, `number_enc`, `new_card`, `pan`
  are redacted keys), a metric or an admin list. `NewCardIn.number` and the service's draft
  are `repr=False`. A 422 for a bad number never echoes it (`card_invalid`).
- **422 bodies** — an app-wide `RequestValidationError` handler (`bootstrap.py`) answers 422 as
  `{"detail": [{type, loc, msg}]}` and drops `input` and `ctx`, so no request body (card
  numbers, trade links) is echoed back by pydantic.
- **Retention** — a deleted card is soft-deleted: a paid request must keep pointing at its
  card for disputes. Erasing old encrypted numbers is M5's retention work.
- **Skinslink's deposit webhook** carries the seller's Steam id; it is never read or logged.

## Where each may appear

| Channel                | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Application logs       | **Never.** `core/logging.py` redacts by key (`steam_id`, `email`, `ip`, `trade_link`, `partner`, `token`, `user_id`, …) and by stem (`*email*`, `*steamid*`, `*_ip`, `*_token`). Use `hash_short()` when a log needs to correlate one person's events                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Prometheus metrics     | **Never as a label.** Labels are bounded `Literal`s (`core/metrics.py`, rule 1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Sentry                 | `send_default_pii=False` (no headers, cookies, user), `max_request_body_size="never"` (no request bodies: the Starlette integration attaches JSON bodies whatever `send_default_pii` says, and its scrubber does not know a card `number`; `before_send` also drops `request.data`) and `include_local_variables=False` (no stack-frame locals) — `core/observability.py`                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| Traces, locals in logs | Off: structlog renders tracebacks with `show_locals=False`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| URLs and query strings | Never carry a trade link or token. Advisory lookups that take one are `POST`. Our own logs drop query strings (below), but Cloudflare and browsers still see full URLs                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Edge and access logs   | Caddy's access log and its error log pass a filter (`(pii_filter)` in `infra/caddy/Caddyfile.prod`): it keeps method, host, path, status, size and duration and deletes the client address, every request and response header and the query string. uvicorn runs with `--no-access-log`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Chat, docs, tests      | Never a real trade-link token or a real person's Steam ID; use redrawn / fake values                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Admin UI               | Shows what an operator needs to resolve an order (M1+); every admin action is audited in `admin_audit_log`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| Third parties          | Steam (Web API) receives the Steam ID and the trade token for the hold check, and its OpenID service sees the sign-in (M1); Waxpeer receives the trade link to check it (M1) and its `partner` and `token` to deliver (M4a); Skinslink receives `partner` and `token` to deliver a Skinslink order, an API order included (ADR-0010, ADR-0017) and sends us nothing we keep about the buyer; LIS-SKINS receives `partner` and `token` to deliver a LIS-SKINS order, an API order included (ADR-0012, ADR-0017) and sends us nothing we keep about the buyer; Skinslink receives `partner` and `token` to price the seller's inventory and send the deposit offer (ADR-0016); acquirers (Click, Payme, Uzum) receive the top-up or order number and amount, never the Steam ID; Uzum sends us the payer's phone (above) |

## Retention

Retention for `users` (deletion via `deleted_at`), orders, and backups is decided with the
modules that own them: M1 for accounts, M5 for backups. M4a deletes nothing: an order, its
trade (with the trade-link snapshot) and its ledger entries are money records.

The order's trade-link **token** is not kept forever (owner decision 2026-10-02): 30 days after
the order reaches a terminal status it is erased, leaving the Steam account and the masked
form (`••••XY`) for disputes; the purchase stays findable at Waxpeer by the order's
`project_id`. Since M4b the scheduler job `orders.erase_trade_links` (22:00 UTC nightly,
`orders.erase`) rewrites `orders.trade_link` to the masked form and stamps
`trade_link_erased_at`; a value that does not parse becomes `erased`. The same job drops a
`verify` outbox row's address a week after it was queued (its link dies after 24 h).
