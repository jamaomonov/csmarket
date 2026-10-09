# 0017. The public purchase API and the USD wallet

- **Status**: Accepted
- **Date**: 2026-10-09
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | data

## Context and problem statement

Resellers (YuPay first) want to buy skins from us over an API, in dollars. The storefront ledger
holds soʻm only. Spec: `docs/superpowers/specs/2026-10-09-public-api-design.md`; delivery in
three plans, A (this ADR's part: the USD wallet), B (keys, buying), C (webhooks, ops).

## Decision drivers

- The API's prices are dollars; no rate in the contract.
- One ledger, one `post` invariant; no float, no second money store.
- An admin decides who gets a dollar wallet; no path from dollars back to soʻm.

## Considered options

1. **A currency column on `wallet_accounts`**, separate dollar accounts, balance checked per currency.
2. **A separate USD ledger** (own tables) beside the soʻm one.
3. **Convert per order** from the soʻm balance at purchase time.

## Decision outcome

**Chosen option:** 1, because the invariant, idempotency keys, row locks and history code carry
over unchanged and a transaction can still be atomic across both currencies.

- **Per-currency ledger.** `wallet_accounts.currency` (`UZS` | `USD`); USD is integer milli-USD
  (1000 = $1) in the same `Numeric(14,0)`. `post` requires SUM(D) = SUM(C) per currency.
- **Two house FX accounts.** One `house_fx` cannot hold two currencies under the
  `(owner_type, owner_id, kind)` key, so `house_fx_uzs` (debit-normal) and `house_fx_usd`
  (credit-normal) are the conversion's counter-accounts; new kinds `user_wallet_usd`,
  `house_payments_received_usd`, `house_adjustments_usd`; tx kinds `fx_convert`, `admin_adjust_usd`.
- **Conversion** at the site rate (`fx.api.current_usd_uzs`, CBU × (1 + `fx_uplift_pct`),
  ADR-0011): `usd_units = floor(amount_uzs × 1000 / rate)`; ledger key `fx_convert:` + sha256 of
  `user_id:Idempotency-Key`. Soʻm to dollars only.
- **The switch.** `users.usd_wallet_enabled`, set by an admin (audited `wallet.usd_switch`). Off
  keeps the money; conversion and API purchases stop. Dollars enter by conversion or by an
  admin's audited credit (`wallet.adjust_usd`).
- **Customer API.** `GET /wallet` gains `usd`; `POST /wallet/convert`; `GET /wallet/entries?currency=`.

### Positive consequences

- Dollar reports come from the ledger: `house_fx_uzs` and `house_fx_usd` say what was converted.
- Plan B debits the USD wallet with the existing `purchase` / `refund` kinds, the account deciding.

- Plan B: the partner API reuses the same ledger and the same buy worker; an API order is a paid
  `orders` row (`channel = api`), so refunds, attention and reconciliation need no new states.

### Plan B consequences (rulings R1–R5)

- **R1 — no nullable site columns.** `price_uzs`, `fx_snapshot_id` and `fx_uplift_pct` stay
  NOT NULL: an API order stores `price_uzs = 0`, the newest FX snapshot (any age; none ever
  recorded is 503 `rate_unavailable`), `fx_uplift_pct = 0`; `price_usd` holds the charged price.
- **R2 — who may issue a key.** A successful top-up **or** `usd_wallet_enabled` (an admin-funded
  client such as YuPay may never top up); otherwise 409 `api_key_not_allowed`.
- **R3 — the token is never stored,** so a replayed issue `Idempotency-Key` answers 409
  `key_already_issued` with the `key_id`, not the token.
- **R4 — the feed is stored as JSON text pages** of 1000 items in Redis (no per-page gzip in the
  app); Caddy gzips the response. A strong ETag per page, 304 on `If-None-Match`.
- **R5 — new failure reasons** `trade_hold` and `price_moved` (Skinslink `hold` /
  `hold_and_permissions` map to `trade_hold`); the partner reads a closed list of refund reasons.
- **Orders are scoped to the key's owner.** `client_order_id` is unique per user among API
  orders (`uq_orders_user_client_order_id`, partial `WHERE channel = 'api'`, migration 0028), so
  a reissued key still reads the old orders and cannot reuse an old id; another user's order is 404. Keys are revoked, never deleted (`orders.api_key_id` is RESTRICT).
- **No external call on the public path.** The feed and offers read our own tables and Redis;
  the trade link is checked for form only; the buy happens in the worker.

### Plan C consequences (rulings R6–R10)

- **R6 — webhooks are an outbox.** `api_webhooks` (one URL per user, it follows reissues) and
  `api_webhook_deliveries` (unique per `(order, event)`). The row and `NOTIFY api_webhooks`
  are written in the transaction of the order's move (`orders.webhook_events`), so an event is
  neither lost nor sent for a rolled-back move. The worker drains it (`webhook_sender`):
  5 s timeout, 10 attempts (1 m, 5 m, 30 m, 2 h, then every 2 h), then `failed`. Delivery is
  at least once and unordered; the payload carries `event_id` and the public order.
- **R7 — the URL is a request we make for someone else, so it is checked hard** (SSRF): `https`
  only, no userinfo / fragment, normalised host, every resolved address public (private,
  loopback, link-local, CGNAT, 198.18/15 and the IPv4-embedding forms are refused), DNS bounded
  at 3 s, checked at save **and before every send**. The connection is pinned to the checked
  address with TLS verified against the hostname; no redirects, no env proxies.
- **R8 — signing.** `HMAC-SHA256` over `{timestamp}.{body}`, key = the UTF-8 bytes of the
  hex SHA-256 of the token. We hold that hash anyway, so no second secret exists; the price is
  that **a reissue changes the signing key at once**, documented for partners.
- **R9 — admin.** The API keys page (list with orders / revenue / cost, card, tariff change,
  revoke; audited `api_keys.tariff` / `api_keys.revoke`) replaces SQL for the tariff. The
  webhook is shown by host only.
- **R10 — refund of Skinslink / LIS-SKINS orders** by an admin, after one supplier call
  ([ADR-0018](./0018-admin-refund-skinslink-lisskins.md)); a partner then reads `refunded` +
  `cancelled_by_support`.
- **Metrics.** `csmarket_public_api_requests_total{route,status}`,
  `csmarket_public_api_orders_total{profile,outcome}`, `csmarket_api_webhooks_total{event,outcome}`
  (`docs/architecture/metrics.md`); labels are bounded and never name a key or a person.
- **PII.** A webhook URL is stored and never logged (host only in logs and admin).

### v1.1 consequences

Spec `2026-10-09-public-api-v1-1-design.md`. Only fields and routes are added.

1. **Limits per key.** Nullable columns on `api_keys` (`NULL` = the default of `limits.py`: read 60,
   order 10, feed 1, check 30); the admin edits them on the key's card, audited `api_keys.limits`.
2. **No hold flag outside.** No new status or field; the outcome comes from the supplier's fact
   only, and the internal review stays in the admin.
3. **The trade-link check is an advisory `POST`** without `Idempotency-Key`, with its own per-key
   `check` limit.
4. **`trade.steam_offer_id` and `trade.seller_name`**, both nullable.
5. **Limits and the IP allow-list carry over on reissue,** like the tariff; four limits, including
   `check_per_min`.
6. **A LIS-SKINS repeat refused while `market/info` shows nothing stays as it is:** the
   `buy_unconfirmed` attention, the order stays `buying`, an admin decides (refunding could pay
   twice). The 30-minute alert tells ops.
7. **Alerts go live:** Alertmanager starts with this release in its own compose profile
   `alerts`; the backup stays in `ops`.
8. **The user edits the IP allow-list in the profile;** the admin sees it read-only.
9. **`ambiguous_trade` is not "several trades of one order"** and changes nothing for the partner.
10. **A link that is not a Steam trade link** answers `200` `bad` / `invalid_link` with no upstream
    call, not 422.
11. **`seller_name` stays in the contract** though it is `null` for API orders today; documented
    as "usually `null`".

### A live check of LIS-SKINS lots (2026-10-10)

Order K4SV9JTD was a partner's buy of a LIS-SKINS lot from the 5-minute snapshot. The lot was
already sold: the worker's `market/buy` got `skins_unavailable`, and the order was paid and then
refunded within 0.3 s. So `POST /public/orders` now asks LIS-SKINS
`GET /market/check-availability` once for a chosen `ls:` lot, **before** anything is written.
It uses the site checkout's `live_price`: a 4 s timeout, a shared 100/min budget, and a 120 s
breaker. The DB connection is released across the call. This is the ninth carve-out in AGENTS
§11. The outcomes:

- **Sold.** A named `offer_id` gets `409 offer_gone`. "Cheapest within max" moves to the next
  offer, which is checked in turn if it is LIS-SKINS too (at most 3 checks).
- **A different live price.** The order is re-quoted for the key's tariff; past
  `max_price_usd` it gets `409 price_above_max`.
- **No answer.** The snapshot price stands, and the worker's `max_price` is the money guard.

A sold lot is never swapped for another one. The partner, like a site buyer, picks a lot for
its float, pattern or stickers, so a substitute would be a different skin (owner, 2026-10-10).

**The offer check, `GET /public/catalog/{item_id}/offers/{offer_id}` (v1.2, the same day).**
A partner such as YuPay charges its buyer first and buys from us after. It now asks right before
the payment whether the offer is still for sale (`available`, `gone` or `unconfirmed`), and at
what price for its tariff.

- A LIS-SKINS lot is asked live. A Skinslink offer answers from the mirror. A lot already gone
  from our tables is `gone` with no call.
- It is not cached, and it shares the key's `check` limit with the trade-link check.
- Both partner paths (this check and `POST /public/orders`) spend their own share of the
  LIS-SKINS check budget: **40** a minute (`lisskins:check:api:*`). The storefront keeps **60**,
  so partners can never starve the site's checkout. 100 in all, as before, out of the key's 200.
- `public_api.offer_check.live_quote` is the one implementation behind both partner paths.

### v1.3: honest refunds and refused links (2026-10-10, YuPay's brief)

- **`sold_out` means the lot was sold or became dearer, nothing else.** Skinslink's
  `seller_too_slow` cancelled YuPay's 1P26ZCTN, and it was refunded as `sold_out`. Every other
  refusal from Skinslink or LIS-SKINS now gets the internal reason `source_refused`, which the
  partner reads as `supplier_refused`. The mapping is in `docs/api/public-v1.md`.
- **LIS-SKINS' refusal code is stored** in `lisskins_purchases.error`, so the reason is no longer
  only in a container log.
- **A link LIS-SKINS refused is remembered for 24 h**, by a SHA-256 of the link, never the link
  itself (`lisskins:link_rejected:*`).
  - `POST /public/tradelink/check` answers `bad` / `rejected_by_market` without an upstream
    call.
  - `POST /public/orders` answers `409 trade_link_rejected` for a named LIS-SKINS lot, and skips
    LIS-SKINS lots when buying the cheapest within the cap.
  - YuPay's buyer was refused four times in a row for a link that Steam, Waxpeer and Skinslink
    accept.
- **The offer check never guesses `gone`.**
  - A lot missing from a stale source (the Skinslink mirror past
    `skinslink_mirror_stale_minutes`, a LIS-SKINS snapshot past its threshold) is
    `unconfirmed`.
  - A Skinslink offer is `available` only from a mirror synced within 30 s, else
    `unconfirmed`. Skinslink has no per-offer check; its change feed is the mirror's source.
- The check limit of YuPay's key is raised to 120 a minute in the admin (an audited key edit),
  not in code.

### Negative consequences

- No dollars back to soʻm: a client who wants out is paid by hand (admin debit).
- A feed refresh lags by up to 60 s, and the feed is 503 for ~400 s only on a cold Redis or after the scheduler was down for more than ~25 minutes (a scheduler restart alone keeps serving the old snapshot for up to 1500 s).
- A webhook that fails all 10 attempts stays failed; the partner falls back to polling.
- Our own server makes outbound requests to partner-chosen hosts; the address checks, the
  pinning and the lack of redirects are the whole defence and must not be loosened.
- We carry the FX gap between the converted rate and the day we buy; the uplift covers it.

## Validation

Unit and integration tests pin the per-currency invariant, the conversion floor, replay and
mismatch, and the switch. In production: the first YuPay credit and `house_fx_*` sums
(`docs/runbooks/public-api.md`).

## References

- [ADR-0006](./0006-wallet-payments-topups.md) — the ledger; [ADR-0011](./0011-fx-uplift.md) — the rate.
