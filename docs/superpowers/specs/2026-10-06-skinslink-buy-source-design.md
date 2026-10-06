# Skinslink as a second buy source — design

- **Status:** draft for the owner's review (2026-10-06). Brainstormed in conversation; every
  section below was approved there (approach **A**: Skinslink beside Waxpeer, Waxpeer untouched).
- **Changes:** spec `2026-10-01-csmarket-design.md` named Skinslink the **sell** side only (§2,
  §17). The owner now wants it as a buy source too; selling through its deposit API stays a later,
  separate spec. ADR-0010 records the change.
- **API:** `https://api.skinslink.com/api/v1`, `X-Api-Key`, JSON envelope
  `{success, message, data}`. Reference: <https://docs.skinslink.com/llm> (read in full,
  2026-10-06).

## 1. Goal and success

Show Skinslink's CS2 offers next to Waxpeer's and buy from whichever the buyer picked, so the
catalogue gets the cheaper of the two without the buyer ever seeing a source. Success:

1. A catalogue card's price is built from the cheaper source's cost; its count adds both.
2. The item page lists both sources' offers in one list sorted by price, same fields.
3. Paying for a Skinslink offer buys it from Skinslink and delivers the skin by a Steam trade
   offer; every failure ends in a refund to the balance or an admin's attention — never a
   double buy, never a buy above our ceiling.
4. With `CSMARKET_SKINSLINK_ENABLED=false` the shop behaves exactly as today.

Non-goals: selling skins (deposits), the catalogue WebSocket, more games than CS2, routing a
buy to another source behind the buyer's back except the one substitute retry (§5).

## 2. Constraints carried in

- AGENTS §6: the word `supplier` is banned in `apps/*/src` (`check-no-yupay.sh`); this design
  says **source** (`waxpeer` | `skinslink`).
- AGENTS §10: never log PII — Skinslink payloads carry the buyer's `steam_id`; the redactor
  already drops `steam_id`; trade links travel only as `partner` + `token` in request bodies
  and are never logged. The API key and secret join the redaction list.
- AGENTS §11: no new synchronous external call on the request path. Skinslink offers come from
  our own mirror (§3); the webhook only enqueues (§6).
- AGENTS §9: every money path has tests for success, retryable failure and idempotent re-call.
- The customer never sees where a skin comes from (AGENTS §12, spec §7).

## 3. The mirror of Skinslink's stock

New module `modules/skinslink/` (client, mirror, purchases, webhook; `api.py` is its interface).

**Table `skinslink_items`** — one row per Skinslink catalogue item (CS2 only):

| column                                     | notes                                                        |
| ------------------------------------------ | ------------------------------------------------------------ |
| `id` text PK                               | Skinslink item id = the `asset_id` passed to Create Purchase |
| `market_hash_name` text                    | as Skinslink spells it                                       |
| `phase` text null                          | Doppler / Gamma Doppler phase (`extended=true`)              |
| `price_usd` numeric(12,6)                  | Skinslink's purchase price                                   |
| `float_value`, `paint_seed`, `inspect_url` | from `extended=true`, nullable                               |
| `image_url` text                           |                                                              |
| `skin_item_id` uuid null FK `skin_items`   | our catalogue item it maps to; `NULL` = not in our catalogue |
| `updated_at`                               |                                                              |

Index `(skin_item_id, price_usd)` for offers and the per-item minimum.

**Keeping it current** (scheduler job `skinslink.mirror`, every 15 s; logic in the module's
service):

1. No cursor, or the last answer said `reset: true` → full download:
   `GET /merchant/purchase/available?game=csgo&full=true&extended=true`; replace the table in
   one transaction; store `last_update_at` as the cursor.
2. Otherwise `GET /merchant/purchase/events?since=<cursor>&game=csgo&extended=true`: apply
   `upsert` (insert/replace by id) and `remove`; store `next` exactly as sent (nanoseconds);
   `more: true` → ask again at once within the same tick.
3. The cursor and `mirror_synced_at` live in one row of `skinslink_state`.

**Mapping to our catalogue:** by `market_hash_name` + `phase`, the same rule `waxpeer_name_of`
applies for Waxpeer; unmapped items are kept (`skin_item_id NULL`) but never shown or priced.

**Staleness:** a mirror older than **10 minutes** (`mirror_synced_at`) is not used — no
Skinslink offers, no Skinslink price — until a tick succeeds. Waxpeer is unaffected.

## 4. Prices and offers

**Catalogue snapshot.** `skin_items` gains `skinslink_min_units` and `skinslink_count`,
written by the existing 5-minute price sync from the mirror (units = USD × 1000, Waxpeer's
unit, so `pricing.quote()` and repricing take either). The item's **cost** becomes the
minimum of `min_auto_units` (Waxpeer) and `skinslink_min_units`; the card's count is
`count_auto + skinslink_count`. Pricing rules, admin overrides and rounding apply unchanged to
that cost. A stale mirror counts as no Skinslink stock.

**Offers (`GET /skins/{slug}/listings`).** Waxpeer offers as today (cache, budget, breaker,
snapshot fallback); Skinslink offers straight from the mirror (no external call). Both become
the same `SkinListingOut`; stickers are empty for Skinslink. Merged, sorted by price, cut to
the page's limit. `degraded` keeps meaning "Waxpeer answered from a fallback".

**Offer id.** `listing_id` becomes a string with a source prefix: `wx:<waxpeer item_id>` or
`sl:<skinslink id>`. `POST /orders` accepts both the new string and a bare integer (read as
`wx:`) for one release, so an open tab keeps working. OpenAPI and the TS client follow.

## 5. Orders and buying

**Order.** `orders` gains `source` (`waxpeer` | `skinslink`, default `waxpeer` for existing
rows) and `offer_id` text (the prefixed id); `listing_id` stays for Waxpeer rows.
`cost_units` / `cost_usd` keep their meaning (our cost ceiling, from the chosen offer).

**Checkout** (`orders/checkout.py`). Re-quotes the chosen offer: a Skinslink offer from the
mirror (it is ≤ 15 s old), a Waxpeer offer as today. ±2 % tolerance as today. If the offer is
gone or moved past tolerance, `next_offer` is the cheapest offer of **either** source.

**Purchase record.** Table `skinslink_purchases`: `order_id` (unique), `purchase_id`
(Skinslink's, nullable until answered), `asset_id`, `status` (Skinslink's word), `offer_id`
(Steam), `fail_reason`, `amount_usd`, `hold_end_date`, `last_polled_at`,
`attention_reason`, timestamps.

**The buy** (worker, `orders` queue, ADR-0007 rules). `drain_paid` routes by `source`:
`waxpeer` → today's path untouched; `skinslink` → `attempt_skinslink_buy`:

1. Take the lease (`orders.buy_lease`).
2. `POST /merchant/purchase` with `game=csgo`, `asset_id`, `partner` + `token` from the
   buyer's trade link, `merchant_tx_id` = the order id, `max_price` = the cost ceiling in USD.
   Skinslink is idempotent on `merchant_tx_id`: a lost answer (timeout, 5xx, crash) is
   resolved by repeating the same call, which returns the stored purchase — never a second buy.
3. Record the answer; the order goes `buying`; the status flow (§6) takes over.

**Failures:**

| Skinslink says                                                                                                                                  | We do                                                                                                   |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `item_sold`, `item_not_available`, `price_changed`, `item_specified_price_not_found`                                                            | one substitute: cheapest offer of the same item, any source, within the ceiling; else refund `sold_out` |
| `trade_link_revoked`, `trade_link_invalid`, `trade_banned`, `profile_private`, `limited_account`, `hold`, `permissions`, `hold_and_permissions` | refund `invalid_trade_link`                                                                             |
| `insufficient_balance`                                                                                                                          | refund `source_low_balance` (renamed from `waxpeer_low_balance`) + alert                                |
| 403 (IP not whitelisted, merchant disabled)                                                                                                     | attention `source_forbidden` (renamed from `waxpeer_forbidden`); the buy stops                          |
| 408, 500, 502, network                                                                                                                          | retry on the next tick (same `merchant_tx_id`)                                                          |
| `duplicate_purchase`, 409                                                                                                                       | look the purchase up by `merchant_tx_id` and adopt it                                                   |

The two renames keep old rows readable (a migration maps the old codes).

## 6. Status flow

**Webhook** `POST /api/v1/skinslink/webhook` (on `bootstrap._exempt_self_authenticating_routes`):

1. Read the body, take `purchase_id` (or `trade_id`), check
   `sign == base64(sha256(str(id) + secret))` in constant time; a bad or missing sign → 403.
2. The signature covers only the id, so the body is **not trusted**: insert a
   `skinslink_checks` row (`purchase_id`) with `NOTIFY skinslink` in one transaction; answer 200. Duplicates are harmless (the check is idempotent).
3. Deposit webhooks (`trade_id`, the future sell side) are answered 200 and ignored.

**Worker queue `skinslink`** drains checks: `GET /merchant/purchase/status?id=…`, then applies
the status. **Scheduler `skinslink.reconcile`** (every 30 s) enqueues a check for every open
purchase not polled for 30 s — the fallback when a webhook is lost.

| Skinslink             | Order / trade                                              | Buyer sees                  |
| --------------------- | ---------------------------------------------------------- | --------------------------- |
| `new`, `pending`      | `buying` / `buying`                                        | «Покупаем»                  |
| `active` + `offer_id` | `trade_sent` / `offer_sent`, offer URL                     | the Steam offer link        |
| `hold`                | stays `trade_sent`                                         | waiting for the hold to end |
| `completed`           | `delivered` / `accepted`                                   | «Получено»                  |
| `failed`, `canceled`  | refund to balance; reason `not_accepted` or the mapped one | «Обмен не состоялся»        |
| `reverted`            | attention `rolled_back` (as Waxpeer's rollback)            | as today                    |

The trade card (`SkinTradeOut`) is filled the same way for both sources; Waxpeer-only fields
(seller, release date) are empty for Skinslink.

## 7. Settings, money, monitoring

Settings: `CSMARKET_SKINSLINK_ENABLED` (default `false`), `CSMARKET_SKINSLINK_API_KEY`,
`CSMARKET_SKINSLINK_SECRET`, `CSMARKET_SKINSLINK_BASE_URL`. Disabled → the mirror job does
nothing, no Skinslink offers or prices, the webhook answers 404. Both keys go to the log
redaction list and `infra/secrets-example/api.env`.

Admin: the dashboard shows the Skinslink balance (`GET /merchant/balance`: available, hold)
beside Waxpeer's; the order page shows the source, the Skinslink purchase id and status.

Metrics (`csmarket_skinslink_*`): API calls by endpoint and outcome, mirror lag seconds,
purchases by final status. Alerts: `SkinslinkMirrorStale` (> 10 min), `SkinslinkLowBalance`,
`SkinslinkBuyFailures`; each links `docs/runbooks/skinslink.md`.

## 8. Testing

- Contract (respx) for every endpoint used: available, events (incl. `more`, `reset`),
  purchase (success, each fail reason, 409, 5xx, timeout), status, balance.
- Mirror: full load, upsert/remove, reset, `more` paging, cursor kept exactly, staleness.
- Prices: cost = min of sources; stale mirror ignored; counts add.
- Offers: merged and sorted; prefixed ids; old integer id accepted.
- Checkout: tolerance, `next_offer` across sources.
- Worker: success, each failure row of §5, lost answer resolved by repeat, substitute once.
- Webhook: good/bad/missing sign, forged body ignored (status comes from the API), duplicates,
  deposit webhook ignored, disabled → 404.
- Reconcile: lost webhook recovered by polling.
- Coverage ≥ 95 % for `skinslink` (added to `check-module-coverage.py`), `orders`, `skins`.

## 9. Documents

ADR-0010 (Skinslink as a buy source; the sell side later), `modules/skinslink/README.md`,
`docs/runbooks/skinslink.md` (keys, IP whitelist, webhook URL, balance top-up, alerts),
`docs/architecture/module-map.md`, a sequence diagram `skinslink-buy.mmd`,
`docs/api/README.md` (prefixed `listing_id`), `docs/security/pii-handling.md` (what we keep
from Skinslink payloads), spec `2026-10-01` §2/§17 pointing here, AGENTS §0/§11 lines.

## 10. Rollout

1. Deploy with `CSMARKET_SKINSLINK_ENABLED=false` — nothing changes.
2. The owner rotates the keys (the ones pasted in chat on 2026-10-06), puts the new ones in
   `secrets/api.env`, whitelists `57.131.198.69` in Skinslink, sets the webhook URL
   `https://api.csmarket.uz/api/v1/skinslink/webhook`, tops up the Skinslink balance.
3. Enable; watch the mirror fill and the catalogue prices; the first test buy goes with the
   first kassa or an admin balance credit.
