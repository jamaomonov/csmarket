# Public API v1.1 — limits per key, outcome by supplier fact, trade-link check, Steam offer id

- **Status:** draft for the owner's review (2026-10-09). The owner's brief
  `csmarket-public-api-v1-1-brief.md` (2026-10-09, revised the same day) fixed the scope; the
  review of the brief and the owner's three answers (below, §2) settled the rest. ADR-0017 gets
  the decisions.
- **Why:** YuPay replaces Waxpeer with csmarket's public API: its storefront reads the feed and
  offers, buys through `POST /orders` and listens to webhooks. Four places stop it working as
  is: a 60-a-minute read limit a live storefront outgrows; `buying` with no word on how long it
  may last; no trade-link check before payment; no Steam offer id to show the buyer.
- **Compatibility:** only fields and routes are added. Existing v1 clients keep working; the
  path stays `/api/v1/public`.
- **Base:** `docs/api/public-v1.md`, ADR-0017, spec `2026-10-09-public-api-design.md`.

## 1. Success

1. An admin sets a key's `read_per_min` to 600, and `GET /me` shows 600.
2. A lost buy answer is settled by asking the supplier and, if it shows nothing, by repeating
   the buy under the same id — never by a timer; both outcomes of a repeat (already there /
   refused) are tested. An API order in `buying` for over 30 minutes raises an alert in the
   ops Telegram chat.
3. `POST /public/tradelink/check` answers `bad` / `private_inventory` for a link to a private
   inventory and `ok` for a working one.
4. A delivered order carries `trade.steam_offer_id`.
5. A user sets the IP allow-list of their key in the profile.

## 2. Decisions

From the brief:

1. **Limits per key.** Nullable columns on `api_keys`; `NULL` = the default of
   `public_api/limits.py`. The admin edits them on the key's card; every change is audited.
2. **No hold flag outside.** No new status or field: a public order reads
   `buying → trade_sent → delivered` or `refunded`. The outcome comes from the supplier's fact
   only; the internal review (`attention_reason`) stays in the admin.
3. **The trade-link check is an advisory `POST`** without `Idempotency-Key` (it writes
   nothing; `POST` keeps the token out of URLs and access logs), with its own per-key limit.
4. **`trade.steam_offer_id` and `trade.seller_name`**, both nullable.

From the review (owner, 2026-10-09):

5. **Limits carry over on reissue,** like the tariff — and so does the IP allow-list (today
   neither the allow-list nor limits would survive a reissue). There are four limits: the
   brief's three and `check_per_min` (§3 of the brief asks for it configurable too).
6. **A LIS-SKINS repeat refused while `market/info` shows nothing stays as it is** (answer 1):
   the `buy_unconfirmed` attention, the order stays `buying`, an admin decides; the 30-minute
   alert (§5) tells ops. Refunding there could pay twice: the first send may have bought.
7. **Alerts go live** (answer 2): Alertmanager is started on the server with this release
   (§7). The backup stays off until its own secrets exist.
8. **The user edits the IP allow-list in the profile** (answer 3), beside the key; the admin
   sees it read-only.
9. **`ambiguous_trade` is not "several trades of one order".** It is a purchase that landed
   on an order someone already moved (refunded, say). The partner already reads the order's
   final status; settling the money is an admin's call. Nothing changes for it.
10. **A link that is not a Steam trade link** answers `200` `bad` / `invalid_link` (no upstream
    call), not 422: a client handles one shape.
11. **`seller_name` stays in the contract** though it is `null` for every API order today
    (neither Skinslink nor LIS-SKINS names the sender; only Waxpeer did). Documented as
    "usually `null`".

## 3. Limits per key

- **Migration `0030_api_key_limits`:** `api_keys.read_per_min`, `orders_per_min`,
  `feed_per_min`, `check_per_min` — `Integer NULL`, each with `CHECK (x IS NULL OR x > 0)`.
- **`limits.py`:** `Bucket` gains `"check"`; `LIMITS` = read 60, order 10, feed 1, check 30.
  `limit_for(key, bucket)` returns the key's column or the default; `enforce` uses it.
  The Redis key stays `public_api:rl:{bucket}:{key_id}` (a new bucket name only).
- **`GET /me`:** `limits` = the effective values, plus `check_per_min` (a new field).
- **Reissue (`keys.issue`):** the new key copies `pricing_profile`, `ip_allowlist` and the
  four limits from the user's latest key.
- **Admin:** `PUT /admin/api-keys/{key_id}/limits` with
  `{read_per_min, orders_per_min, feed_per_min, check_per_min, reason}` — each `null` (the
  default) or 1–10 000; `Idempotency-Key` like the tariff route; audited `api_keys.limits`
  with the old and new values and the reason. The card shows the effective values and marks
  the defaults; a form edits them. The card also shows the IP allow-list, read-only.
- After the release the owner (or the agent, on the owner's word) sets YuPay's key to
  `read_per_min=600`, `orders_per_min=30`, `feed_per_min=1`.

## 4. IP allow-list in the profile

- **Site route** `PUT /api/v1/me/api-key/ip-allowlist`, body `{"ip_allowlist": ["…"]}`,
  `Idempotency-Key` required; the signed-in user's live key; 404 `api_key_missing` without one.
- Entries: an IPv4 / IPv6 address or CIDR, normalised with `ipaddress.ip_network(strict=False)`
  and deduplicated; at most 20; an empty list = any address. A bad entry: 422
  `ip_allowlist_invalid` naming its index. The allow-list governs the API only, never the
  site, so a user cannot lock themselves out of fixing it.
- `GET /me/api-key` returns `ip_allowlist`.
- **Web:** the API-key card in the profile gets an "Allowed IP addresses" block: the list,
  a textarea (one per line), Save; an inline «где найти?» hint (the server's outgoing address;
  empty = any). ru / uz / en.
- The addresses are the partner's infrastructure, not a person's: stored and shown to the
  owner and the admin, never written to logs (`docs/security/pii-handling.md`).

## 5. Outcome by the supplier's fact

What the code already does (spec 2026-10-06 §5, 2026-10-07 §6; ADR-0010, ADR-0012) and keeps:

| Case                                                      | Today                                                                                                                                                                    | Public view                |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------- |
| Lost buy answer, Skinslink                                | after `order_unconfirmed_minutes` (10) with nothing under our `merchant_tx_id`, the same id is sent again; Skinslink answers the stored purchase, a new one or a refusal | `buying`, then the outcome |
| Lost buy answer, LIS-SKINS                                | the same with `custom_id`; LIS-SKINS refuses a known id                                                                                                                  | as above                   |
| LIS-SKINS refuses the repeat, `market/info` shows nothing | `buy_unconfirmed` attention, admin decides (decision 6)                                                                                                                  | `buying`                   |
| `source_forbidden` (403)                                  | buy stays pending, retried every 60 s; no refund                                                                                                                         | `buying`                   |
| `rolled_back` after delivery                              | attention only; no refund                                                                                                                                                | `delivered`                |
| `ambiguous_trade`, `audit_divergence`                     | attention only                                                                                                                                                           | unchanged                  |

No timer refunds anything. This release adds:

- **Tests** that pin it for API orders: a Skinslink repeat answered "already there" continues
  the order; a repeat refused / sold out refunds to the **USD wallet** with the reason; a
  LIS-SKINS repeat seen by `market/info` continues; one refused and unseen stays `buying` with
  the attention.
- **Metric** `csmarket_public_api_orders_buying_oldest_seconds` (gauge, no labels), set by the
  scheduler's `orders.health` job: the age, from `created_at`, of the oldest API order whose
  public status is `buying` (`paid` / `buying`, or `failed` / `returned` without a refund);
  0 when there is none.
- **Alert** `PublicApiOrderBuyingLong` (`infra/prometheus/alerts/orders.yml`):
  `max(csmarket_public_api_orders_buying_oldest_seconds{job="scheduler"}) > 1800` for 5 min,
  severity `warn`, runbook `public-api.md#an-api-order-buying-for-over-30-minutes`. Unlike
  `OrdersBuyingStuck`, it counts orders with an open attention too: a partner waits on them.
- **Docs** (`public-v1.md`, the partner guide): `buying` lasts as long as the supplier takes
  to answer; a refund comes only from a supplier's refusal or cancellation (or our support);
  a rollback after delivery is not refunded.

## 6. Trade-link check

- **Route** `POST /api/v1/public/tradelink/check`, body `{"trade_link": "…"}` (≤ 512 chars),
  answer `{"verdict": "ok" | "bad" | "unavailable", "reason": … | null}`. Bucket `check`
  (default 30 a minute); 401 / 403 / 429 like every route.
- **Same checker as the site** (`users/tradelink.check_trade_link`): Waxpeer `check-tradelink`
  - Steam `GetTradeHoldDurations`, the shared 600 s cache by SHA-256 of the link, the 60 s
    breaker. The checker factory moves from `users/routes.py` to `users/api.py` so both routes
    use it. No new external call path: AGENTS.md §11's second carve-out gains this route, and
    its path joins the latency alerts' `handler` regexes.
- **Mapping:** internal `invalid` → `invalid_link`, `private` → `private_inventory`,
  `trade_ban` → `trade_ban`, `hold` → `hold`, new internal `not_found` → `not_found`;
  `verdict None` (`unavailable`) → `unavailable`, `reason null`. A link that does not parse →
  `bad` / `invalid_link` with no call.
- **`not_found`:** `_reason_for` maps a Waxpeer text with "not found" / "does not exist" to
  `not_found`. The site's own answer maps `not_found` to its `invalid`, so the site and its
  schema do not change. Waxpeer's exact wording is unknown: an unrecognised text stays
  `invalid_link`.
- **Waxpeer key:** the check needs `CSMARKET_WAXPEER_API_KEY` on the server (Waxpeer buying is
  off, its key still checks links). Without it every answer is `unavailable`; the deploy
  verifies it is set.
- The token is never logged; the docstring says why the route takes no `Idempotency-Key`.

## 7. Alerts on the server

- `docker-compose.prod.yml`: `alertmanager` joins a new profile, `profiles: [ops, alerts]`;
  `backup` stays `[ops]`. The server's `.env` gets `COMPOSE_PROFILES=alerts`, so deploys keep
  Alertmanager up and the backup off.
- The owner writes `ALERT_BOT_TOKEN` and `ALERT_CHAT_ID` into `secrets/alertmanager.env` on
  the server themselves (never in chat). Then `up -d alertmanager`, and a test alert
  (`amtool alert add …`, `first-deploy.md` step 9) must reach the chat.
- `docs/runbooks/first-deploy.md` step 9 and `deploy.md` say which profile is which.

## 8. `trade` fields

`PublicTradeOut` gains:

- `steam_offer_id: str | null` — Skinslink `skinslink_purchases.offer_id`, LIS-SKINS
  `lisskins_purchases.steam_trade_offer_id`, Waxpeer `skin_trades.trade_id`. Both supplier
  columns already exist and are filled; no migration.
- `seller_name: str | null` — Waxpeer's `skin_trades.seller["name"]`; `null` otherwise.

`trade` is still present only while the order reads `trade_sent` or `delivered`. The webhook
payload is the same object, so it carries both fields.

## 9. Documentation

- `docs/api/public-v1.md`: limits per key and `check_per_min`; the outcome rule (§5); the
  check route with a curl example; the new `trade` fields; the new codes
  (`ip_allowlist_invalid` on the site route); a **Changelog** section dated 2026-10-09.
- `docs/api/partner-guide.md` (docs.csmarket.uz) the same, partner-facing; `make gen-api`.
- ADR-0017: a "v1.1 consequences" section (decisions 1–11).
- `docs/runbooks/public-api.md`: raising a key's limits; the IP allow-list; what to do on
  `PublicApiOrderBuyingLong`; the check returning only `unavailable`.
- `docs/architecture/metrics.md`, `cache-keys.md` (the `check` bucket), AGENTS.md §11 and
  §0, the `public_api` and `users` module READMEs.

## 10. Testing

- Limits: a key's value beats the default per bucket; `NULL` falls back; the `check` bucket
  counts apart from `read`; `GET /me` shows the effective values; reissue carries limits and
  the allow-list; the admin route validates, audits and replays.
- IP allow-list: normalising, deduplicating, the 20 cap, a bad entry's 422; the API then
  refuses another address (`ip_not_allowed`); the web form (Vitest).
- Outcome: the four cases of §5's tests; the gauge's age and its 0.
- Check: `ok`; `bad` with each reason; `invalid_link` with no upstream call; `unavailable` on
  an upstream failure and with the breaker open; a cache hit makes no call; the bucket's 429.
- `trade`: `steam_offer_id` from Skinslink, LIS-SKINS and Waxpeer rows; `seller_name` from
  Waxpeer and `null` otherwise; the webhook payload carries them.
- Coverage ≥ 95 % for `public_api` and `orders` (the module gates already enforce it).

## 11. Delivery

One plan, one branch (`public-api-v1-1`), merged into local `main`. Push, deploy, the YuPay
limits and the alert secrets on the owner's word.
