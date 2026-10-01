# skins

The CS2 catalogue and everything Waxpeer (spec §3.2). **M1 shipped the Waxpeer client's
first call**; M2 adds the catalogue, import, price sync and listings; buying arrives in M4.

- **Public interface:** `skins.api` — `WaxpeerClient`, `WaxpeerError`,
  `WaxpeerUnavailableError`, `WaxpeerRateLimitedError`, `SnapshotRow`. Other modules import nothing else from here.
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
  at most 50 names; returns Waxpeer's `items` map (name -> listings). 20 calls a minute.
- **`WaxpeerRateLimitedError`** (HTTP 429, `retry_after_seconds`) subclasses
  `WaxpeerUnavailableError`: a rate limit is an outage to callers that do not care which.
- **The API key rides the query string** (`?api=…`), so a request URL is never logged —
  only method, path and status. `httpx`/`httpcore` loggers are capped at WARNING in
  `core.logging`, and exception text from `httpx` is never logged either (it carries the
  URL); log the exception type name.
- **Nothing Waxpeer-branded reaches a browser.** Callers translate results into their own
  wire shapes (e.g. `users` maps reasons to `invalid | private | trade_ban`).
- **Tests:** `apps/api/tests/contract/test_waxpeer_check_tradelink.py` and `test_waxpeer_catalogue.py`
  (recorded shapes in `tests/fixtures/skins/`; respx; never the
  real API, never a real trade-link token).

## Pricing (M2)

- **`pricing`** — `PricingRules` (retail brackets, expenses, liquidity bands, category and
  weapon pp, min margin, floor, UZS rounding, Steam cap) and `quote()`; `DEFAULT_RULES` is
  the owner's launch seed. Retail only: there is no merchant channel. A stored document
  with a stray `b2b` key still loads (extra keys are ignored).
- **`repricing`** — `reprice_rows` writes `sell_price_usd` / `discount_percent` for every
  active row after each price tick and each rules write. `hidden` rows are priced too, so
  unhiding is instant. `lock_pricing` serialises writers (advisory xact lock).
- **`settings`** — `load_rules` (Redis `skins:pricing`, TTL 3600 -> `skin_pricing_rules`
  row 1 -> defaults), `save_rules` (Postgres only; the caller `publish_rules` after commit),
  `enabled_categories`.

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
