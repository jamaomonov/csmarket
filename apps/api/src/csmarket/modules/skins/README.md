# skins

The CS2 catalogue and everything Waxpeer (spec §3.2). M1 shipped the Waxpeer client's first
call; **M2 is the browsable catalogue** (import, price sync, stored sell prices, read API,
listings, admin); M4a adds the Waxpeer purchase client and the dev fake (below). Decisions:
[ADR-0005](../../../../../../docs/decisions/0005-skins-catalogue-fx-and-indexing.md),
[ADR-0007](../../../../../../docs/decisions/0007-orders-buying-trades.md) (buying). Operations:
`docs/runbooks/skins-catalogue.md`, `docs/runbooks/waxpeer.md`.

## What the module owns

| Table                 | Holds                                                                                                                                                                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skin_items`          | One row per `(market_hash_name, phase)`: ByMykel metadata, our `slug` (a URL, assigned once), the Waxpeer price columns, the Skinslink and LIS-SKINS roll-ups, `active`, `hidden`, the stored `sell_price_usd` / `discount_percent` |
| `skin_pricing_rules`  | The single row (`id = 1`) of the pricing document the admin editor will write (M4b); absent = `DEFAULT_RULES`                                                                                                                       |
| `skin_search_aliases` | Admin-edited search aliases (alias -> text), none seeded                                                                                                                                                                            |

Migration `0003_skins_catalog`; `0018_skinslink` adds `skinslink_min_units` and
`skinslink_count`, written only by `skinslink.rollup` (ADR-0010); `0022_lisskins` adds
`lisskins_min_units` and `lisskins_count`, written by the LIS-SKINS snapshot and kept honest by
`lisskins.rollup` (ADR-0012). `SkinItem.stock_count` = `count_auto + skinslink_count +
lisskins_count`. `hidden` is the admin's flag and is never written by the import or the price
sync. `phase` is `''` when an item has none, never NULL.

- **Public interface:** `skins.api` — `WaxpeerClient`, `WaxpeerError`,
  `WaxpeerUnavailableError`, `WaxpeerRateLimitedError`, `SnapshotRow`, and the purchase
  side (`TradeClient`, `WaxpeerTradeClient`, `trade_client`, `WaxpeerBuy`, `WaxpeerTrade`,
  `WaxpeerSeller`, `parse_trade`, `WaxpeerBuyRefusedError`, `WaxpeerForbiddenError`,
  `LOOKUP_MAX_IDS`), and the source-neutral offers (`Offer`, `Source`, `offer_id_of`,
  `parse_offer_id`, `from_listing`, `merge_offers`, `TIE_ORDER`, below) with `canonical_name`. Other modules import
  nothing else from here; the catalogue is reached through HTTP routes, not through `api.py`.
- **`waxpeer.WaxpeerClient`** — transport only, async `httpx`, inject `client=` in tests.
  `check_tradelink(url) -> str | None` (`POST /v1/check-tradelink`):
  `None` when the link works, else Waxpeer's reason text (`info` on `success: true`,
  `msg` on `success: false`). An HTTP error status raises `WaxpeerError`; no API key, a
  network failure or a 200 whose body is not a JSON object raises `WaxpeerUnavailableError`
  (no traffic without a key) — an unreadable answer is an outage, never a reason.
- **`iter_snapshot_rows()`** — `GET /v1/prices/snapshot?format=csv`, streamed line by line
  (read timeout 300 s) into `SnapshotRow(item_id, name, price_units, auto)`; units 1000 = $1.
  A header without `item_id,name,price,auto` raises `WaxpeerError` once; rows with an
  unknown or zero price are skipped and counted (`waxpeer.snapshot.done`).
- **`prices()`** — `GET /v1/prices?minified=0`: one dict per Waxpeer name (type, rarity,
  image) — the sync's source for the first-seen taxonomy.
- **`search_listings(names)`** — `GET /v2/search-items-by-name` with `delivery_details=1`,
  at most 50 names; returns Waxpeer's `items` map (name -> list of listings). 20 calls a minute.
- **`WaxpeerRateLimitedError`** (HTTP 429, `retry_after_seconds`) subclasses
  `WaxpeerUnavailableError`: a rate limit is an outage to callers that do not care which.
  `_request` (the `POST`/`GET` helper under `check_tradelink` and the purchase calls)
  raises it on 429 too; `params` follow the key and a list value repeats its key.
- **`WaxpeerUnavailableError` is not a `WaxpeerError`.** Catch it (and the rate limit)
  before `WaxpeerError` when the branches differ.

## Buying at Waxpeer (M4a)

- **`waxpeer_trades.WaxpeerTradeClient(WaxpeerClient)`**, behind the `TradeClient` protocol;
  `trade_client(settings)` builds it with `waxpeer_buy_timeout_seconds` (or `timeout_seconds=`);
  `request_trade_client()` — a FastAPI dependency — with `REQUEST_LOOKUP_TIMEOUT_SECONDS` (4 s)
  for the one request-path lookup (the admin refund, ADR-0007 Y).
  - `buy_one_p2p(item_id=, price_units=, partner=, token=, project_id=) -> WaxpeerBuy(id,
price_units)` — `GET /v1/buy-one-p2p`, never over `price_units`; `project_id` is our
    order id. A success without an integer `id` / `price` is `WaxpeerUnavailableError`.
  - `check_project_ids(ids) -> list[WaxpeerTrade]` — `GET /v1/check-many-project-id?id=…&id=…`,
    at most 100 ids (more raises `ValueError`, never truncated); unknown ids are absent;
    no ids makes no call; an answer without a readable `trades` list is unavailable,
    never "absent".
  - `balance_units() -> int` — `GET /v1/user` → `user.wallet`; anything but an integer is
    unavailable (never a guessed balance).
- **Errors, classified (ruling R6):** `WaxpeerBuyRefusedError(WaxpeerError)` — 200
  `success: false`, `new_price_units` when Waxpeer named one; `WaxpeerForbiddenError(WaxpeerError)`
  — HTTP 403 (IP whitelist); `WaxpeerRateLimitedError` — 429; `WaxpeerUnavailableError` —
  no key, network, unreadable answer (the buy may have happened: resolve by lookup, never by
  buying again); `WaxpeerError(status=…)` — any other HTTP status.
- **`parse_trade(raw) -> WaxpeerTrade`** (frozen pydantic): `status` −1 when unparsable;
  `send_until` / `seller_steam_joined` epoch seconds; `release_date` ISO 8601 with an
  offset (naive → `None`); empty `penalties` → `None`; `seller` = `WaxpeerSeller(name,
avatar_url, level, joined_at)`. The buyer's `for_steamid64` is dropped here (both it and
  `seller_steam_id` are also on the log redaction list).
- **Observability:** `csmarket_waxpeer_calls_total{endpoint, outcome}`
  (`docs/architecture/metrics.md`); one `skins.waxpeer.call` log line per call with
  `endpoint`, `outcome`, `status` only — never a URL (key, `partner`, `token`) or a body.
- **Tests:** `tests/contract/test_waxpeer_purchase.py` (recorded shapes 2026-09-28, redrawn
  link and Steam IDs), `tests/unit/test_waxpeer_trade_parse.py`.
- **The API key rides the query string** (`?api=…`), so a request URL is never logged —
  only method, path and status. `httpx`/`httpcore` loggers are capped at WARNING in
  `core.logging`, and exception text from `httpx` is never logged either (it carries the
  URL); log the exception type name.
- **Nothing Waxpeer-branded reaches a browser.** Callers translate results into their own
  wire shapes (e.g. `users` maps reasons to `invalid | private | trade_ban`).
- **Tests:** `apps/api/tests/contract/test_waxpeer_check_tradelink.py` and `test_waxpeer_catalogue.py`
  (recorded shapes in `tests/fixtures/skins/`; respx; never the
  real API, never a real trade-link token).

## Dev Waxpeer fake (`waxpeer_fake.py`, ruling R13)

- **On with `CSMARKET_WAXPEER_FAKE=true`** (the dev compose default); `Settings` refuses it in
  prod and `fake_active(settings)` re-checks `is_prod`. Then `trade_client()` (worker buys,
  scheduler sweeps and gauges), `request_trade_client()` (the admin refund's lookup, 4 s),
  `listings.search_client()` (item page, checkout) and `users.routes.tradelink_checkers()`
  all return `FakeTradeClient(get_redis())`.
- **`FakeTradeClient(redis)`** implements `TradeClient`, `SearchClient` and the trade-link
  checker. `buy_one_p2p` always succeeds: a trade with a random id, `status=0`, `price` = the
  asked units, kept in `skins:waxpeer:fake:trade:{project_id}` (hash, 7 days); a second buy
  under one `project_id` adds a second trade (the sweeps then see an ambiguous lookup).
  `check_project_ids` keeps the real contract (≤ 100 ids, `ValueError` above, unknown ids
  absent) and reports each trade as of now: 0 → 2 with a 10-digit `trade_id` after 3 s → 4
  with `send_until` 30 min after the offer went out (6 s). `balance_units` reads
  `skins:waxpeer:fake:balance` (default 10 000 000 = $10 000; a buy does not spend it).
  `search_listings` is always `WaxpeerUnavailableError` (the snapshot serves), and
  `check_tradelink` always passes. Redis down reads as a Waxpeer outage; under the dev
  routes (set the balance, accept / decline / roll back) it is a 503 (`FakeUnavailableError`).
- **Dev routes** (404 unless dev login is on and the fake is on): `act()` behind
  `POST /dev/orders/{number}/trade` — `accept` sets `release_date` = now + 7 days on a status-4
  trade, `decline` sets 6 + `reason="Buyer failed to accept"`, `rollback` sets 6 +
  `penalties={"rollback_fee": price}` after an accept; `dev_routes.py`'s
  `POST /dev/waxpeer/balance {units}` sets the balance.
- **The price sync is not faked** (ruling T): with a key set, the scheduler's
  `skins.price_sync` job keeps the real read-only client, so dev prices stay live while
  buys go to the fake.
- **With the fake off and a real key, a local buy is a real purchase** with the shop's
  Waxpeer money (`docs/runbooks/waxpeer.md`).
- **Tests:** `tests/integration/test_waxpeer_fake.py` (the sweeps driven end to end).

## Pricing (M2)

- **`pricing`** — `PricingRules` (retail brackets, expenses, liquidity bands, category and
  weapon pp, min margin, floor, UZS rounding, Steam cap, the cheap tail) and `quote()`;
  `DEFAULT_RULES` is the owner's launch seed. The cheap tail (`cheap_tail`, ADR-0015) applies
  under `max_cost_usd` of cost: `sticker_pp` replaces `category_pp["stickers"]`, and
  `low_liquidity_pp` replaces the last liquidity band (`min_count` 0). `null` turns it off. Retail only: there is no merchant channel. A stored document
  with a stray `b2b` key still loads (extra keys are ignored).
- **`repricing`** — `reprice_rows` writes `sell_price_usd` / `discount_percent` for every
  active row after each price tick and each rules write. The cost is the cheapest present
  source (`cost_units(*units)`: `min_auto_units`, `skinslink_min_units`,
  `lisskins_min_units`); the liquidity count is `stock_count` (every source's lots), the same
  sum the card, the item page, checkout and the `popular` sort use. `hidden` rows are priced too, so
  unhiding is instant. `lock_pricing` serialises writers (advisory xact lock).
- **`settings`** — `load_rules` (Redis `skins:pricing`, TTL 3600 -> `skin_pricing_rules`
  row 1 -> defaults), `read_rules` (Postgres only, no cache fill — the preview), `save_rules`
  (Postgres only; the caller `publish_rules` after commit), `enabled_categories`.

## Pricing editor (M4b, ruling R8)

`pricing_routes` (admin only) over `pricing_admin`:

- `GET /admin/skins/pricing` — the saved document, who saved it and when, active and
  overridden item counts, the rate.
- `PUT /admin/skins/pricing` (required `Idempotency-Key`) — `lock_pricing` → `save_rules` →
  `reprice_rows` (every active item) → audit `skins.pricing.save {items_repriced}` → replay
  row → **commit** → `publish_rules` → `bump_catalog_version`. A failure before the commit
  leaves the old rules in Postgres and Redis and the old prices; invalid rules are 422 with
  the validator's reason.
- `POST /admin/skins/pricing/preview` — a `Quote` with every component and the soʻm price,
  for an item by `slug` (its cost, taxonomy and overrides fill the blanks) or a made-up one
  (`cost_usd` + `category`), under the saved or a draft document. Writes nothing (no row, no
  cache, no audit), so it is keyless.
- `PUT /admin/skins/items/{slug}/pricing` (required key) — `margin_override_pp` (−100..500)
  and `fixed_price_usd` (0..100 000, honoured while it covers cost + min margin), `null`
  clears; reprices that item only; audit `skins.item.override`. `GET /admin/skins/items`
  gains `overridden` and the item's cost and overrides.

## Catalogue import (M2)

- **`bymykel`** — the daily import from ByMykel/CSGO-API: eleven JSON files (`skins_not_grouped`
  plus the non-skin files in `taxonomy.FILE_CATEGORIES`) become `CatalogRow`s and are upserted by
  `(market_hash_name, phase)` in batches of 1 000, one transaction per file.
  `upsert_items` writes metadata columns only: **never** `slug` (a URL, assigned on insert),
  `hidden` (the admin's flag) or any price column, so a re-import can run at any time. An
  unchanged catalogue reports `changed = 0`. A non-200 answer raises (`fetch_file` calls
  `raise_for_status`); nothing is written for the failed file onward.
- **`job_status`** — the last outcome of the catalogue jobs (`JOB_IMPORT`, `JOB_PRICE_SYNC`)
  in Redis `skins:job:{job}` (JSON, no TTL, Redis errors swallowed). `error` is our own label
  (the exception type name), never upstream text. The scheduler's `skins.catalog_import`
  writes it; the admin status card reads it.
- **Scheduler job** `skins.catalog_import` runs every `CSMARKET_SKINS_IMPORT_INTERVAL_HOURS`
  (24), first run 120 s after start, and is skipped while `CSMARKET_SKINS_SYNC_ENABLED` is
  false. It never raises: a failure is logged and recorded.
- **Tests:** `tests/unit/test_skins_bymykel.py`, `tests/integration/test_skins_import.py`
  (respx, never the real GitHub), `tests/integration/test_skins_job_status.py`;
  `apps/scheduler/tests/test_skins_catalog_import.py`.

## Price sync (M2)

- **`prices`** — folds Waxpeer's CSV snapshot onto `skin_items` every
  `CSMARKET_SKINS_SNAPSHOT_INTERVAL_MINUTES` (5). `aggregate_stream` reduces the ~1.2 M rows to one
  `PriceAggregate` per canonical `(name, phase)` in one pass; `apply_prices` then, in the caller's
  transaction, updates only rows whose `price_hash` changed, deactivates rows absent from the
  snapshot (price columns cleared) and inserts a `source='stub'` row for a name the catalogue has
  never seen. **Only `auto` listings set a price** (`min_auto_units`, `count_auto`, the ten cheapest
  in `cheapest_auto`); manual listings count in `count_all` / `min_all_units` only. A name is
  `active` when it has an auto listing, except a Doppler without a phase. A Steam price of 0 is
  stored as NULL (unknown). `apply_prices` never writes `hidden`, metadata, `slug` or the stored
  sell price; writers set `updated_at` explicitly.
- **`sync_prices`** — one tick: stream the snapshot, read `/v1/prices`, then take
  `lock_pricing`, apply, roll Skinslink's mirror up (`skinslink.api.rollup`: per item the
  cheapest Skinslink price and count; an item with Skinslink stock stays active without a
  Waxpeer listing, and loses only its Waxpeer columns when Waxpeer drops it), `reprice_rows` with rules read fresh from Postgres, commit, and bump the
  catalogue version. A snapshot with an `auto` listing for fewer names than `MIN_SNAPSHOT_SHARE`
  (half) of the active catalogue is **refused** (`ApplyResult.refused`) before the lock: a
  truncated body, or an `auto` column whose format changed, must not read as "everything sold
  out". Nothing is written and the previous prices stand. Only rows active now are candidates
  for deactivation, so the `IN (…)` list never grows with the inactive catalogue.
- **`source_prices`** (ADR-0010, ADR-0012) — the non-Waxpeer sources on their own ticks.
  `sync_source_prices` (scheduler `sources.prices`, was `skinslink.prices`; every 120 s, first
  run 105 s): `lock_pricing`, forget Waxpeer stock while Waxpeer buying is off,
  `skinslink.api.rollup`, `lisskins.api.rollup`, `reprice_rows`, commit, bump the catalogue
  version. It runs while Skinslink or LIS-SKINS is active, or while an earlier roll-up of
  either remains to clear, so their prices appear and leave without a Waxpeer tick.
  `sync_lisskins` (scheduler `lisskins.snapshot`, every 5 min): streams LIS-SKINS' export with
  no transaction open (it takes minutes), then in one transaction under `lock_pricing` writes
  the snapshot (`lisskins.api.apply_snapshot`; a refused one writes nothing), rolls it up,
  reprices and bumps the catalogue version. The Waxpeer `sync_prices` tick runs both roll-ups
  too.
- **`cachekeys`** — `catalog_version` / `bump_catalog_version` for Redis `skins:catalog:ver`
  (`docs/architecture/cache-keys.md`). Kept apart from `prices` so the read path never imports the
  Waxpeer client.
- **Scheduler job** `skins.price_sync` (first run 60 s after start, `max_instances=1`) is skipped
  unless `CSMARKET_SKINS_SYNC_ENABLED` is true **and** `CSMARKET_WAXPEER_API_KEY` is set. It never
  raises: Waxpeer trouble, a crash or a refused tick is logged by exception type name (never
  Waxpeer text) and recorded under `JOB_PRICE_SYNC` (a refused tick as `error="thin_snapshot"`).
- **Tests:** `tests/unit/test_skins_prices.py`, `tests/integration/test_skins_price_sync.py`,
  `test_skins_price_edge_cases.py`, `test_skins_reprice_lock.py`;
  `apps/scheduler/tests/test_skins_price_sync.py`.

## Public read API (M2)

Postgres only — no route here calls Waxpeer except `GET /{slug}/listings` (see **Live listings**). Every read
leaves out `hidden` rows and categories outside `CSMARKET_SKINS_CATEGORIES`; the API is always
on (no feature flag, ruling Q1).

- **`service`** — `list_items` (filters; keyset `(sort value, id)` cursor for `price`, `-price`,
  `discount`, `popular`; `q` switches to trigram similarity with an offset cursor after
  `expand_aliases`), `facets` (categories counted catalogue-wide, the rest scoped to `category`;
  weapons led by `WEAPON_PRIORITY`, each with its `category` and the `image` of its
  dearest Covert skin (else the dearest) for the filter menu; rarities by `RARITY_TIER`, agents' `teams` only inside a
  category), `suggest`, `get_item` (a sold-out item still resolves; an unknown, hidden or
  disabled-category slug is `NotFoundError`), `family` (every visible wear / StatTrak / Souvenir
  twin). A bad cursor is a 422.
- **`routes`** (`/skins`): `GET /catalog` (`category, weapon` (one model, or up to 30
  comma-separated, sorted for the cache key)`, exterior, stattrak, souvenir,
rarity, team, min_uzs, max_uzs, q, sort` default `-price`, `cursor`, `limit` 1..100 default
  48), `GET /facets?category=` (an unknown category is a 422), `GET /suggest?q=`,
  `GET /{slug}` (card + `cheapest` from the last tick's ten cheapest auto listings, re-quoted
  with the live rules, + `family`). Cards show the stored `sell_price_usd` and, at the CBU rate
  (`usd_uzs_rate` -> `fx.api.current_usd_uzs`), `price_uzs` rounded up to `uzs_round_to`.
  `min_uzs` / `max_uzs` keep exactly the cards whose rounded-up `price_uzs` is inside them
  (`pricing.min_usd_for_uzs` / `max_usd_for_uzs`, whole cents). **Without a fresh rate**
  `price_uzs` is `null` and soʻm bounds are ignored, not guessed (ruling Q3). Image hosts are rewritten to `CSMARKET_SKINS_IMAGE_HOST`.
- **Page cache:** catalogue, facets and suggest bodies sit 60 s in Redis under
  `skins:{catalog|facets|suggest}:{ver}:{sha1}` — `ver` is the catalogue version, so a price tick
  or a hide expires them all at once; the digest covers the query and the rate. Every Redis error
  is swallowed: without Redis each request builds its page.
- **`seo_routes`** (`/skins/seo`, mounted before `/skins` in `api/v1/router.py`):
  `GET /slugs?offset&limit` (≤ 5 000) -> `SkinSlugsOut {items, total}`, alphabetical, the same
  set the catalogue shows — the sitemap source.
- **`schemas`** — the public DTOs; nothing in them names Waxpeer. Money is a string.
- **Slugs** (`naming.slug_for`, `slugs.resolve`): lower-case ASCII; a name whose plain slug is
  already taken by a different item gets six hex characters of its own identity appended. A
  slug is assigned once on insert and never changes, because it is a URL.
- **Tests:** `tests/unit/test_skins_cursor.py`, `tests/integration/test_skins_catalog_routes.py`,
  `test_skins_facets_scoped.py`, `test_skins_catalog_resilience.py` (no rate, Redis down).

## Admin catalogue (M2)

`admin_routes` (`/admin/skins`, `require_admin` on the router; DTOs in `admin_schemas`):

- `GET /catalog/status` -> `CatalogStatusOut`: `items_total`, `items_active`, `items_hidden`,
  `prices_updated_at` (the newest tick), `import_job` / `price_sync_job` (`job_status.read_job`,
  ruling Q6), `fx` (`{usd_uzs, fetched_at, source}` or `null` without a fresh rate),
  `sync_enabled` and `waxpeer_key_set` (a bool, never the key).
- `GET /items?q=&hidden=&limit=` -> `AdminSkinItemsOut`: `q` (2..80) folded by
  `naming.search_text` and matched as an escaped `ILIKE` substring of `search_text`; `hidden`
  filters; `limit` 1..100 (20); hidden and inactive items included; most listings first, then
  slug.
- `PATCH /items/{slug}` `{hidden}` -> `AdminSkinItemOut` (ruling Q4): off every public read at
  once, still priced by the sync, so unhiding is instant. Unknown slug: 404.
- `GET /aliases`, `PUT /aliases/{alias}` `{text}` -> `AliasOut`, `DELETE /aliases/{alias}` ->
  204 (404 if absent). Ruling Q13: admin-edited, none seeded. The alias is trimmed and
  lower-cased, one word of 1..64 letters, digits or hyphens (no space, no `_`: `expand_aliases`
  substitutes whole words, so a phrase would never match); the text is trimmed and
  lower-cased, 1..128.
- **Every write** takes an optional `Idempotency-Key` (`core.idempotency`, scopes
  `admin.skins.item:{item id}`, `admin.skins.alias:{alias}`, `admin.skins.alias.delete:{alias}`),
  records one `admin_audit_log` row (`admin/README.md`), commits, then bumps
  `skins:catalog:ver` so every cached public page expires. A replay writes nothing.
- **Tests:** `tests/integration/test_skins_admin_catalogue.py`.

## Live listings

`GET /skins/{slug}/listings` -> `SkinListingsOut {items, degraded}` is the one advisory carve-out
that calls Waxpeer from a request (AGENTS §11); `listings.listings_for` decides how, in order:

1. fresh Redis `skins:listings:{slug}` (90 s) -> `degraded: false`;
2. if the breaker `skins:wax:breaker` is closed and the process-wide budget
   (`skins:wax:budget:{minute}`, `CSMARKET_SKINS_LISTINGS_BUDGET_PER_MINUTE` = 18, 0 without an API
   key) has room: one `search_listings([waxpeer_name_of(item)])` with a 4 s timeout
   (`CSMARKET_SKINS_LISTINGS_TIMEOUT_SECONDS`). Only `auto` listings are kept, sorted by
   `(price, id)`, cached 90 s fresh and 1 h stale. A 429 or outage opens the breaker for 2 min; any
   other error just falls through;
3. stale Redis `skins:listings:{slug}:stale` -> `degraded: true`. A cached entry that no longer
   decodes into `Listing` (shape drift) counts as a miss, never a 500;
4. the snapshot's `cheapest_auto` (no float, stickers or inspect link) -> `degraded: true`.

It never raises for a Waxpeer problem, and logs only the exception type name (the API key rides
Waxpeer's query string). Each row is re-quoted with the live rules (`pricing.quote`) and shown in
soʻm at the CBU rate. Nothing Waxpeer-hosted reaches a browser: a sticker image is kept only on a
Steam CDN host (`*.steamstatic.com`, `*.akamaihd.net`, rewritten to `CSMARKET_SKINS_IMAGE_HOST`,
`images.steam_image_only`; a `/apps/730/icons/…` icon path goes to the `cdn.` twin of that
host, the only one serving it), else `null`; `inspect_url` only when it is a `steam://` link
(`listings.steam_inspect_url`), checked at parse and again on the way out. The route sits behind its own
`ip_guard` bucket `skins-listings` (60 per window); an unknown or hidden slug is a 404 before any
Waxpeer call. Redis keys: `docs/architecture/cache-keys.md`. Tests:
`tests/unit/test_skins_listings.py`, `tests/integration/test_skins_listings_route.py`.

**Two sources (ADR-0010).** The route adds Skinslink's offers of the item from our own mirror
(`skinslink.api.offers_for`; none while Skinslink is off or the mirror is stale; no external
call, no stickers) and merges both by price (`offers.merge_offers`, Waxpeer first on a tie: its
delivery is instant). `degraded` still means "Waxpeer answered from a
fallback". Every offer carries a string `listing_id` naming its market: `wx:<Waxpeer item_id>`
or `sl:<Skinslink asset id>` (`offers.offer_id_of`); `offers.parse_offer_id` reads it back and
still reads a bare positive integer as `wx:` for one release (`docs/tech-debt.md`). The
customer never sees the source. Tests: `tests/unit/test_skins_offers.py`,
`tests/integration/test_skinslink_offers.py`.

**Three sources (ADR-0012).** LIS-SKINS' lots come from `lisskins_offers`
(`lisskins.api.offers_for`; none while off or stale; no external call) as `ls:<LIS-SKINS skin
id>`, with float, seed, inspect link and stickers as LIS-SKINS names them; sticker images pass
`images.steam_image_only` on the way out (anything off Steam's CDN is dropped, the name stays).
`merge_offers` sorts every source's offers by price, ties by `TIE_ORDER` (Waxpeer, Skinslink,
LIS-SKINS), and shows one Steam asset once — the cheapest (then tie-winning) offer of it.
Checkout re-checks a chosen `ls:` lot live (`orders/README.md`, ADR-0012). Tests:
`tests/integration/test_lisskins_offers.py`, `test_lisskins_listings_route.py`.

## Cache keys

All in [`docs/architecture/cache-keys.md`](../../../../../../docs/architecture/cache-keys.md); none
holds PII. Owned here: `skins:pricing`, `skins:catalog:ver`,
`skins:{catalog|facets|suggest}:{ver}:{sha1}`, `skins:listings:{slug}` (+ `:stale`),
`skins:wax:breaker`, `skins:wax:budget:{minute}`, `skins:job:{import|price_sync}`, and the
`ip_guard` bucket `skins-listings`. Redis is never required for a page to render.

## Dev seed

`make seed-skins` (`python -m csmarket.scripts.seed_skins_dev`) loads about 60 curated ByMykel
items from `csmarket/scripts/dev_skins/*.json` with deterministic fake listings through the real `apply_prices`
and `reprice_rows`, and writes a `source='dev'` rate of 12 700 soʻm if there is none. The Waxpeer
key works only from the prod IP, so local work and e2e use this. It is repeatable, refuses to run
in prod, and treats the fake snapshot as the whole market: other catalogue rows go inactive, so
use it on a dev database only.

## Tests and fixtures

Unit: `tests/unit/test_skins_*.py`. Integration: `tests/integration/test_skins_*.py` (Postgres and
Redis testcontainers; respx for GitHub and Waxpeer, never the real ones). Contract: respx
recordings of Waxpeer's shapes in `tests/fixtures/skins/`, used by `tests/contract/`. A fixture
never holds a real trade-link token. Scheduler jobs: `apps/scheduler/tests/test_skins_*.py`.

## Inspect links (2026-10-07)

`inspect.decode_inspect(url)` reads CS2's self-contained inspect links
(`…csgo_econ_action_preview%20<hex>`: XOR key byte, protobuf `CEconItemPreviewDataBlock`,
CRC checksum) offline: asset id, defindex, paint index and seed, float, stickers and charms
(`def_index`, slot, wear). ~99.9 % of Skinslink's links are of this kind; an old `S…A…D…`
link, a bad checksum or anything else is `None`. Our own ~120 lines, cross-checked against the
`cs2inspect` library (GPL-3.0, not a dependency) on 2 000 real links. `skin_items.def_index`
(migration `0021`, written by the ByMykel import for `stickers` and `keychains`) and
`stickers.applied_cards` turn a `def_index` into a name and an image.
