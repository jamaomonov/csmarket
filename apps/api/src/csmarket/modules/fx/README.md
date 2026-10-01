# fx

The USD/UZS rate the catalogue prices with. New and small; written here, not ported (ruling Q3).

**Owns:** table `fx_snapshots` (`id`, `usd_uzs numeric(12,4) > 0`, `source`, `fetched_at`),
the CBU fetch (`cbu.fetch_usd_uzs`), and the Redis copy `fx:usd_uzs`
(`docs/architecture/cache-keys.md`).

**Interface (`api.py`):** `current_usd_uzs`, `refresh_usd_uzs`, `record_snapshot`,
`fetch_usd_uzs`, `CbuError`, `UsdUzs`, `FxSnapshot`.

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
- No admin override yet (M3 may add one). M4 orders reference `fx_snapshots.id`.

**Job:** `fx.refresh` in `apps/scheduler` — every `CSMARKET_FX_REFRESH_INTERVAL_MINUTES`
(60), first run 20 s after start. It only times the work; the logic is `refresh_usd_uzs`.
