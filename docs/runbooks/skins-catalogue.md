# Runbook — the skins catalogue

The catalogue is ours (ByMykel import); Waxpeer supplies prices and live offers; the rate
comes from CBU. Three scheduler jobs keep it fresh. This runbook covers running them by
hand, reading `/admin`, and the failure modes. Design: ADR-0005.

All commands run on the VPS in `~/opt/csmarket` (`IMAGE_TAG` is pinned in `.env`; never
export one by hand — `docs/runbooks/deploy.md`).

## First launch order

1. Secrets are set (`CSMARKET_WAXPEER_API_KEY`, `CSMARKET_SKINS_SYNC_ENABLED=true`) and the
   VPS IP is on the Waxpeer account's whitelist.
2. Migrate: `docker compose -f docker-compose.prod.yml exec api alembic upgrade head`.
3. Run the import (below), then the rate refresh, then the price sync. An empty catalogue has
   nothing to price, and without a rate the site shows dollars.
4. Open `https://admin.csmarket.uz` -> Catalogue. Check: items total in the tens of
   thousands, a recent price update, a CBU rate, no red job.
5. Open `https://csmarket.uz/` and one item page. Prices are in soʻm.

The scheduler also runs all three on its own after start (fx 20 s, price sync 60 s, import
120 s), so after a deploy this is usually already done: only check.

## Run a job by hand

```bash
# ByMykel import (daily job)
docker compose -f docker-compose.prod.yml exec scheduler python -c \
  "import asyncio; from csmarket_scheduler.jobs.skins_catalog_import import run; asyncio.run(run())"

# Waxpeer price sync (every 5 min; streams ~1.2 M rows, takes a minute or two)
docker compose -f docker-compose.prod.yml exec scheduler python -c \
  "import asyncio; from csmarket_scheduler.jobs.skins_price_sync import run; asyncio.run(run())"

# CBU rate (hourly job)
docker compose -f docker-compose.prod.yml exec scheduler python -c \
  "import asyncio; from csmarket_scheduler.jobs.fx_refresh import run; print(asyncio.run(run()))"
```

Each job never raises: it logs, records its outcome in Redis `skins:job:{import|price_sync}`
(the Catalogue page reads it) and returns. The fx job prints `True` or `False`. Read logs with
`docker compose -f docker-compose.prod.yml logs --since 15m scheduler`. A job is skipped
(logged `skins.import.skipped` / `skins.prices.skipped`) while `CSMARKET_SKINS_SYNC_ENABLED`
is false; the price sync also needs the Waxpeer key.

## Reading the Catalogue page

The «Состояние» card, top of the page (the item search and «Синонимы для поиска» sit below it):

| Line                                   | Healthy                                                                                         |
| -------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Скинов в каталоге / В продаже / Скрыто | total and on sale in the tens of thousands; hidden is what you hid                              |
| Цены обновлены                         | within the last ~10 minutes                                                                     |
| Каталог                                | «Каталог обновлён», within the last day                                                         |
| Цены                                   | «Цены обновлены»; «Waxpeer прислал неполный список — цены остались прежними» is `thin_snapshot` |
| Курс ЦБ                                | a rate and its fetch time; «Курса нет — цены показываются в долларах» means no fresh rate       |
| Обновление цен выключено               | `sync_enabled` is false on this server (the key itself is never displayed)                      |

## Failure modes

### `thin_snapshot` on the price sync

The price sync refuses a snapshot that has an `auto` listing for fewer than half of the
active catalogue (a truncated or empty Waxpeer body, or a changed format of the CSV `auto`
column, would otherwise read as "everything sold out"). Nothing is written; the previous
prices stand and the site keeps working with them. Log: `skins.prices.refused` with `names`
(names seen) and `priced` (names with an `auto` listing) — many names but `priced` near 0
points at the `auto` column, not at a short body.

1. Wait for the next tick (5 minutes); most are a transient Waxpeer hiccup.
2. If it repeats: run the sync by hand and read the log. Check the Waxpeer status and that
   the key is valid.
3. A real, large drop in Waxpeer's catalogue (not a glitch) is rare; if the import has just
   run on a very different catalogue, check that first. Do not lower the threshold in
   production without the owner.

Prices age while the sync is refused. Item pages stay correct for what Waxpeer would sell
because live offers are fetched separately (next section).

### Waxpeer 403 "whitelist your IP"

The key works only from the IP on the Waxpeer account. The sync logs
`skins.prices.failed error=WaxpeerError`. The VPS IP is not on the whitelist (new server, new
IP, a changed egress). Add the current VPS IP at Waxpeer, then run the price sync by hand. Do
not test the key from a laptop: it will 403 there by design (dev uses `make seed-skins`).

### Live offers degraded

`GET /skins/{slug}/listings` answers `degraded: true` when Waxpeer is limiting or down: the
page then shows the last cached offers, or the cheapest from the last price tick, without
floats or stickers. It recovers by itself: the breaker (`skins:wax:breaker`) opens for 2
minutes after a 429 or an outage. The `ApiWaxpeerLatency` alert covers slow lookups
(`docs/runbooks/traffic-surge.md`).

### No rate, or a rate older than 7 days: the site shows dollars

Without a fresh CBU rate the API returns `price_uzs: null`, the pages fall back to USD and
soʻm filters are ignored. The rate counts as missing when the newest `fx_snapshots` row is
older than 7 days (`CSMARKET_FX_MAX_AGE_DAYS`) or there is none. Check, in this order:

1. The Catalogue page's rate card (value and fetch time).
2. Scheduler logs for `fx.refresh.failed` (error type and reason) or `fx.refresh.crashed`.
3. CBU reachability from the VPS:
   `docker compose -f docker-compose.prod.yml exec scheduler python -c "import httpx; print(httpx.get('https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/', timeout=10).status_code)"`.
   A `CbuError` also means the answer was not one plausible USD row (1 000 to 100 000 soʻm).
4. The table: `make psql` is dev only; on the VPS run
   `docker compose -f docker-compose.prod.yml exec postgres psql -U <user> -d <db> -c "select usd_uzs, source, fetched_at from fx_snapshots order by fetched_at desc limit 5"`.
   Read-only; never edit this table by hand.

Then run the fx job by hand (above). A day-old rate is normal: the job adds a row only when
the rate changed or the newest row is 20 h old. A cached copy in Redis (`fx:usd_uzs`, 24 h)
is refreshed by the job.

## Hide an item

Catalogue page -> find the item -> «Скрыть». It is audited (`admin_audit_log`). What users see:

- the **item page 404s at once** (it is not cached);
- the **grid, suggest and facets can still show it for up to 60 seconds** (web data cache);
- the **sitemap can still list it for up to 1 hour**;
- the price sync keeps pricing a hidden item, so «Показать» brings it back instantly.

Hide is not delete: nothing is lost. To remove an item from the shop for good, leave it
hidden.

## Add a search alias

Catalogue page -> Aliases: a short word people type («ак») and the text it stands for
(«ak-47»). One word per alias, letters, digits or hyphens; the alias and the text are stored
lower-case. Aliases replace whole words in the search box only. A new alias works for new
searches within a minute (cached pages expire on the next catalogue version bump, which an
alias edit makes).

## Dev and CI data

`make seed-skins` loads about 60 priced items without Waxpeer. It refuses to run in
production and marks other catalogue rows inactive: never run it against a shared
database.
