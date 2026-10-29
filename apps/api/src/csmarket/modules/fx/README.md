# fx

The USD/UZS rate the catalogue prices with. New and small; written here, not ported (ruling Q3).

**Owns:** table `fx_snapshots` (`id`, `usd_uzs numeric(12,4) > 0`, `source`, `fetched_at`),
the CBU fetch (`cbu.fetch_usd_uzs`), the fallback fetch (`fallback.fetch_fallback_usd_uzs`,
open.er-api.com, ADR-0028), the admin's «Курс вручную» (`admin_routes.py`), and the Redis copy `fx:usd_uzs`
(`docs/architecture/cache-keys.md`).

**Interface (`api.py`):** `current_usd_uzs`, `refresh_usd_uzs`, `refresh_with_fallback`,
`rate_age`, `record_snapshot`, `fetch_usd_uzs`, `fetch_fallback_usd_uzs`, `CbuError`, `UsdUzs`, `FxSnapshot`.

**Rules**

- Postgres is the record, Redis is a copy read first. A Redis error (or a corrupt copy)
  falls through to the newest snapshot; it is never fatal.
- 7-day rule: a snapshot older than `CSMARKET_FX_MAX_AGE_DAYS` (7) is no rate. Callers then
  show dollars and ignore soʻm filters.
- 20-hour rule: a refresh with an unchanged rate adds a row only when the newest row is
  at least 20 h old; a changed rate always adds one.
- `refresh_usd_uzs` commits itself, so Redis never points at a rolled-back snapshot.
  `record_snapshot` only flushes.
- The CBU answer must be one plausible USD row (1 000 to 100 000 soʻm); anything else is a
  `CbuError` and the previous snapshot keeps serving.
- **Sources** (`fx_snapshots.source`): `cbu`; `er-api` — the fallback, asked only when the CBU
  fails and the newest rate is `CSMARKET_FX_FALLBACK_AFTER_HOURS` (12) old (cbu.uz refuses our
  EU server since 2026-10-22, ADR-0028); `manual` — the admin's «Курс вручную»
  (`POST /admin/fx/rate`, keyed, audited `fx.rate.manual`, 1 000..100 000). A fresh rate — a
  manual one too — is never replaced by the fallback. M4a orders reference `fx_snapshots.id`.
- Uplift (ADR-0011): `current_usd_uzs` returns the buyer's rate, `cbu_rate × (1 +
CSMARKET_FX_UPLIFT_PCT / 100)` to 2 places (`UsdUzs.rate`; `cbu_rate` and `uplift_pct`
  beside it). Snapshots and the Redis copy keep the CBU rate. Dollar prices and costs never
  see it; an order stores the uplift it used (`orders.fx_uplift_pct`). Prod: 1
  (`docker-compose.prod.yml`); default 0.

**Job:** `fx.refresh` in `apps/scheduler` — every `CSMARKET_FX_REFRESH_INTERVAL_MINUTES`
(60), first run 20 s after start. It only times the work; the logic is `refresh_with_fallback`. Every run sets
`csmarket_fx_rate_age_seconds` (alerts `FxRateStale` > 26 h, `FxRateExpiring` > 5 days).
