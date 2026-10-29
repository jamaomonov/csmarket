# PII handling

The owner's rule, verbatim in substance: **never log PII — Steam ID, email, IP, trade-link
token.** Order numbers and amounts are fine. This file lists what personal data csmarket
holds, where it may appear, and where it never may. Update it with any change that adds a
field, a log line, a metric or a third party that sees one of these values (`AGENTS.md` § 5).

## Inventory

| Data                               | Stored in                                                                 | Arrives in | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Steam ID (SteamID64)               | `users.steam_id`                                                          | M1         | The identity. Public on Steam, still personal here: it links a person to purchases. Never logged (redactor key `steam_id` and stem `*steamid*`)                                                                                                                                                                                                                                                                                                                                                                                                     |
| Display name, avatar URL           | `users.display_name`, `users.avatar_url`                                  | M1         | Copied from Steam at sign-in                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Email                              | `users.email` (optional); `email_outbox.address` (a `verify` letter only) | M1, M4b    | Order letters go only to a verified address (`email_verified_at`, set by the confirmation link). Resolved at send time; order letters store no address. Sent to Resend (the processor) with the letter. Never logged                                                                                                                                                                                                                                                                                                                                |
| Trade link                         | `users.trade_link`; a snapshot in `orders.trade_link` (M4a)               | M1         | Its `token` is a **credential**: anyone holding it can send that account offers. `partner` is the account id. Returned only to its owner (`GET /me`); never logged. `POST /public/tradelink/check` sends a partner's buyer's trade link (token included) to Waxpeer `check-tradelink` and Steam `GetTradeHoldDurations` even when no order follows; only a SHA-256 of the link is the cache key, and the link or token is never logged or stored                                                                                                    |
| API key (ADR-0017)                 | `api_keys.token_hash`, `api_keys.ip_allowlist`                            | plan B     | Only the SHA-256 of the `csm_…` token is stored; the token is shown once and never logged (the redactor masks values starting `csm_` and the `authorization` header; logs carry the key's uuid only). The optional allow-list (v1.1: set by the user in the profile, `PUT /me/api-key/ip-allowlist`) holds the customer's own server addresses, the partner's infrastructure rather than a person's: stored, shown to the owner and to admins, never written to logs (only their count is). Revoked keys are kept (`orders.api_key_id` is RESTRICT) |
| Partner webhook URL (ADR-0017)     | `api_webhooks.url`, `api_webhook_deliveries.payload`                      | plan C     | The URL is the partner's endpoint (a path may carry a secret). It is stored, **never logged** and never shown in the admin: logs and the admin card carry the **host only**. Log lines of a delivery hold the delivery id, event, outcome and host; never the URL, body or signature. A payload is the public order view: no trade link, no market name, no Steam id. Deliveries are kept with the order                                                                                                                                            |
| Buyer trade links of third parties | `orders.trade_link` of an API order                                       | plan B     | An API client sends **its own buyer's** trade link with every purchase, so the account may hold many other people's links (`partner` + `token` credentials). Same rules as any order link: validated for form only, passed to the supplier, never logged, masked in the admin, and erased with the **30-day** job below (`orders.erase_trade_links`, `channel` makes no difference). The public order read does not return the link                                                                                                                 |
| Client IP                          | **not stored** in Postgres                                                | M0         | Rate-limit counters only (below)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Trade seller (public)              | `skin_trades.seller` (jsonb)                                              | M4a        | The Waxpeer seller's public Steam profile: name, avatar URL, Steam level, account age. Shown to the buyer on the order page and to admins. Never the seller's Steam ID (not stored; `seller_steam_id` is on the redaction list)                                                                                                                                                                                                                                                                                                                     |
| Payer phone, card type             | `uzum_transactions.payment_source` (jsonb)                                | M3         | What Uzum's `/confirm` sends besides the envelope (`phone`, `cardType`, `paymentSource`, …). Stored for reconciliation; never logged (redactor key `payment_source`, stem `*phone*`); admin shows only the source label and the phone masked (`+998••••••67`, `admin.payments_kassa.mask_phone`)                                                                                                                                                                                                                                                    |

### Client IP

- The coarse limiter (slowapi, M0) keeps per-IP, per-route counters **in the API process's
  memory** for its window (one minute by default). Nothing is written to disk.
- The storefront's request-time renders pass the visitor's IP to the API in
  `X-Storefront-Client-Ip` over the internal compose network only (ADR-0003, SEC-01); it is
  used as the rate-limit key like any client IP and never logged or stored. Caddy strips the
  header from outside traffic.
- `ip_guard` (M1) keeps per-IP counters in **Redis** under keys that expire with their window
  (60 s by default). Never in Postgres, never in a column.
- The trade-link verdict cache (M1) is keyed by a **hash** of the link, never the link; its
  value is the verdict and reason only.
- In `ip_guard` keys the address appears only as `hash_short(ip)` (12 hex characters), and a
  subject (the user id) as a SHA-256 prefix. Keys live one window (60 s). Catalogue:
  `docs/architecture/cache-keys.md`.
- The webhook sender connects to the address it checked and sends the partner's `Host`; its
  failures are logged as `http_<code>` / `timeout` / `connect` / `private` / `invalid` with the host only.
  Metric labels are the event name and the outcome (`csmarket_api_webhooks_total`).
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
  admin card shows the trade link whole (owner, 2026-10-19: admins copy it to check or resend a
  trade; the admin API is admin-only and never logs it). Metric `csmarket_kassa_rejections_total` is labelled
  by kassa and reason only.
- **Admin orders API (M4a):** the order page and the «Обмены» row show the order's trade-link
  snapshot whole (`trade_link`; owner, 2026-10-19 — earlier masked), an erased one as the
  masked text it is stored as; the orders list rows carry no link at all. The order actions' audit payloads are an attention reason or an
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

### Reviews (ADR-0023)

- **Review text** — free text the user typed; may hold anything. Stored as typed (trimmed), never
  logged, never in an audit payload or a metric label, rendered as text. Shown publicly only when
  the review is good (4–5★), not hidden by an admin and the public page is on.
- **Steam display name and avatar** — shown on the public page beside a published review (already
  public on Steam). Reviews of a deleted account (`users.deleted_at`) are not shown.
- **The admin's resolve note** — staff text; kept out of audit payloads too.
- **The replay copy** — `PUT /reviews/{kind}/{number}` keeps its answer, text included, in
  `idempotent_responses` (scope `reviews.put:<user id>`) so a retried send replays it. Each send
  or edit leaves one such row; the 24 h replay window (`IDEMPOTENCY_KEY_TTL_SECONDS`) has no
  reaper yet, so these copies stay until one is built — an erasure flow must delete them with the
  review.
- There is no erasure flow yet: a user's review is not deleted on request.

### Payout cards (ADR-0016)

- **Card number** — `payout_cards.number_enc` + `number_nonce`: encrypted with `core.crypto`
  under the purpose `csmarket:payout-card:v1` (a stolen dump alone yields nothing). In the
  clear: `last4` and the type. The full number is returned only by
  `POST /admin/sales/payouts/{id}/reveal`, to an admin, audited every time
  (`sales.card.show` / `sales.card.copy`, payload `last4`), and is never stored as an
  idempotency replay, never in a letter, a log (`card_number`, `number_enc`, `new_card`, `pan`
  are redacted keys), a metric or an admin list. `NewCardIn.number` and the service's draft
  are `repr=False`. A 422 for a bad number never echoes it (`card_invalid`).
- **P2P card number** (spec 2026-10-19-p2p-topup) — `p2p_cards.pan_ciphertext` + `pan_nonce`:
  the owner's receiving card, sealed with `core.crypto` (purpose `p2p_card_pan`); the admin sees
  `•••• last4` only; the full number goes only to a signed-in buyer with an open request
  (`TopupOut.p2p`). Never in an audit payload, a replay row or a log (the add-card replay key
  keeps the last four).
- **P2P notifications** — `p2p_incoming.raw_text` / `source_text`: the bank's message for the
  owner's card (amount, masked card, the payer bank's label, balance). Admin views only; never
  logged (logs carry the amount and last4 at most). Telegram user ids (the owner's, the HUMO
  bot's) live in `p2p_settings`, never in logs or audits.
- **Card fingerprint** (2026-10-12, migration 0033) — `payout_cards.number_fp`: HMAC-SHA256
  of the 16 digits under a key HKDF-derived from `CSMARKET_APP_ENC_KEY` with the purpose
  `csmarket:payout-card-fp:v1` (`sales.cards.card_fingerprint`). It finds the same card on
  other accounts for the admin's «Риски» block without decrypting anything. A dump without
  the app key cannot test a guessed number against it (a plain hash could be brute-forced
  over the card space). It is never logged, never in a response (the admin sees only the
  names of the other accounts), never in a metric. Cards saved before 0033 get it from
  `python -m csmarket.scripts.backfill_card_fp` (it decrypts in memory and prints a count
  only); the key never reaches SQL, so the migration cannot fill it.
- **Reveal** — since 2026-10-12 only a `to_pay` request reveals its number (a decided request
  no longer needs it), and a reveal claims the request for the admin.
- **Seller's Steam link** — the admin's payout page (`risk.steam_url`) carries the seller's
  Steam profile URL (the steamid64 the admin user page already shows); admin only, never
  logged.
- **422 bodies** — an app-wide `RequestValidationError` handler (`bootstrap.py`) answers 422 as
  `{"detail": [{type, loc, msg}]}` and drops `input` and `ctx`, so no request body (card
  numbers, trade links) is echoed back by pydantic.
- **Article views and likes** (ADR-0025, migration 0042) — a view is deduplicated in Redis by
  `sha256(daily salt + ip + article id)` until midnight UTC; the salt is random per day and lives
  only in Redis, the IP is never stored or logged. An anonymous like sets the `csm_aid` cookie (a
  random UUID, HttpOnly, SameSite=Lax, one year) and is stored by that id; a signed-in like by the
  user id (erased with the account, `ON DELETE CASCADE`). Neither id is logged.
- **Payout receipts** (ADR-0024, migration 0041) — `payout_proofs.data` and `.name`: an
  admin's screenshot or PDF of a transfer may show the card, the recipient's name and the bank
  account. Kept in the database (and so in the nightly encrypted backup), served only to an admin
  by `GET /admin/sales/payouts/{id}/proofs/{proof_id}` with `Cache-Control: no-store`, never by a
  public link, never shown to the seller. The audit row keeps the id, type and size; the
  idempotency replay keeps the file's SHA-256 and name, never its bytes; nothing logs either.
  Caddy's access log drops headers (the name travels in `X-File-Name`). Deletion only within
  10 minutes of upload; retention follows the payout's (M5).
- **Retention** — a deleted card is soft-deleted: a paid request must keep pointing at its
  card for disputes. Erasing old encrypted numbers is M5's retention work.
- **Skinslink's deposit webhook** carries the seller's Steam id; it is never read or logged.

## Where each may appear

| Channel                | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Application logs       | **Never.** `core/logging.py` redacts by key (`steam_id`, `email`, `ip`, `trade_link`, `partner`, `token`, `user_id`, …) and by stem (`*email*`, `*steamid*`, `*_ip`, `*_token`). Use `hash_short()` when a log needs to correlate one person's events                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Prometheus metrics     | **Never as a label.** Labels are bounded `Literal`s (`core/metrics.py`, rule 1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Sentry                 | `send_default_pii=False` (no headers, cookies, user), `max_request_body_size="never"` (no request bodies: the Starlette integration attaches JSON bodies whatever `send_default_pii` says, and its scrubber does not know a card `number`; `before_send` also drops `request.data`) and `include_local_variables=False` (no stack-frame locals). Query strings are stripped from breadcrumbs, spans and the request (`before_breadcrumb`, `before_send_transaction`, `before_send`): the httpx integration records the raw query of every outgoing call, and Waxpeer's carries its API key and the buyer's trade-link `partner`/`token`; the Steam callback's carries the Steam ID. Request headers, cookies and env are dropped (the storefront secret, the visitor's IP, the bearer token), and a URL's query is cut out of exception messages (`httpx.HTTPStatusError` quotes the full URL) — `core/observability.py`                                                                                                                                                                                                                                                                                                                             |
| Traces, locals in logs | Off: structlog renders tracebacks with `show_locals=False`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| URLs and query strings | Never carry a trade link or token. Advisory lookups that take one are `POST`. Our own logs drop query strings (below), but Cloudflare and browsers still see full URLs                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Edge and access logs   | Caddy's access log and its error log pass a filter (`(pii_filter)` in `infra/caddy/Caddyfile.prod`): it keeps method, host, path, status, size and duration and deletes the client address, every request and response header and the query string. uvicorn runs with `--no-access-log`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| Chat, docs, tests      | Never a real trade-link token or a real person's Steam ID; use redrawn / fake values                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Admin UI               | Shows what an operator needs to resolve an order (M1+); every admin action is audited in `admin_audit_log`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Third parties          | Steam (Web API) receives the Steam ID and the trade token for the hold check, and its OpenID service sees the sign-in (M1); Waxpeer receives the trade link to check it (M1) and its `partner` and `token` to deliver (M4a); Skinslink receives `partner` and `token` to deliver a Skinslink order, an API order included (ADR-0010, ADR-0017) and sends us nothing we keep about the buyer; LIS-SKINS receives `partner` and `token` to deliver a LIS-SKINS order, an API order included (ADR-0012, ADR-0017) and sends us nothing we keep about the buyer; Skinslink receives `partner` and `token` to price the seller's inventory and send the deposit offer (ADR-0016); acquirers (Click, Payme, Uzum) receive the top-up or order number and amount, never the Steam ID; Uzum sends us the payer's phone (above); Google Analytics 4 (storefront on csmarket.uz only, `apps/web/src/lib/analytics.ts`) receives page views, the visitor's IP for coarse geo (Google does not store it) and funnel events carrying an order or sale number, an amount in soʻm and a skin's slug and English name — never a Steam ID, user id, email or trade link; no `user_id` is set, and the Steam callback strips its `openid.*` query before the tag loads |

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

## Referrals (2026-10-27)

- `referral_attributions` links a referred account to its partner's account. Admins see it on
  the user card; the partner never sees who it brought: its page and `/referrals/me/rewards`
  carry amounts and dates only — no name, Steam ID or order number.
- A link visit is counted per visitor per day by a salted digest in Redis
  (`referrals:visited:*`); the IP is never stored or logged. The `csm_ref` cookie (HttpOnly,
  30 days, API host) holds only the partner's public code and is cleared at sign-in.
- Logs name the partner's code and amounts, never the buyer.

## «Мои сделки» (2026-10-29)

- `desk_deals.trade_link` (a trader's trade link with its token), `trader` (a name or handle)
  and `note` are the owner's own records, readable only with the `desk` role. Never logged:
  `desk.*` logs carry codes and error types only. The link goes to Skinslink with the deposit,
  as the shop's sales do.
