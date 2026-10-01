# M2 — Skins Catalogue, Prices in Soʻm, Storefront and SEO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anyone can browse csmarket.uz's CS2 catalogue — the home page is the filterable
catalogue, every item has its own page with live offers, category and weapon landings and
sitemaps open the site to Google, and prices show in soʻm at the CBU rate; nothing can be
bought yet.

**Architecture:** The `skins` module is ported from YuPay by allow-list: three tables
(`skin_items`, `skin_pricing_rules`, `skin_search_aliases`), ByMykel import (daily),
Waxpeer price snapshot (5 min) with stored sell prices from the pricing rules, a Postgres +
Redis read API, and a cached, budgeted, degradable live-listings proxy. A new, small `fx`
module keeps the CBU USD/UZS rate (`fx_snapshots` + Redis). Admin gets a catalogue page
(job status, hide an item, search aliases) with every action in a new `admin_audit_log`.
The storefront ports YuPay's skins pages onto `/`, `/item/[slug]`, `/category/[c]`,
`/weapon/[w]` and sitemaps, with real 404s.

**Tech Stack:** FastAPI · SQLAlchemy 2 async · Alembic · Postgres 16 (`pg_trgm`) · Redis 7 ·
httpx · APScheduler · pytest + testcontainers + respx + hypothesis · Next.js 15 (RSC) +
next-intl v4 · Vite + React 19 + TanStack Query · Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-csmarket-design.md` — §2 (decisions 6, and the
inherited skins decisions), §3.2 (`skins`, `fx`, `admin` rows), §5 (`skin_*`,
`fx_snapshots`, `admin_audit_log`), §7.3, §8, §9, §10 (web `/`, `/item`, landings,
sitemaps; admin catalogue), §11, §13, §14, §15 row M2. Rulebook: `AGENTS.md` (§4–§12, §14).

**Source material (read-only):** `/Users/macbook_uz/Projects/yupay`, written below as
`yupay:<path>`. Backend files live under `yupay:apps/api/src/yupay/modules/skins/`
(written `yupay-skins:<file>`), web under `yupay:apps/web/src/`, shared TS under
`yupay:packages/utils/src/`. Copy a Python file through the rename filter from the repo
root — `sed -f scripts/port-rename.sed <yupay file> > <dst>` — then apply the deltas the
task lists. Never write to YuPay.

## Global Constraints

- **Owner decisions for M2 (2026-10-01, in conversation):** (D1) the CBU USD/UZS rate moves into M2 — the catalogue shows soʻm from day one; (D2) the catalogue is open to search engines from the M2 deploy (robots allow, sitemaps served); (D3) the item page has **no** buy button or buy panel in M2 — price and live offers only.
- **Our catalogue is ours** (ByMykel/CSGO-API); Waxpeer supplies only prices and listings; **nothing Waxpeer-branded reaches a browser** (no Waxpeer names, CDN images or ids in copy); seller name and inspect link may be shown. Only `auto` listings count. (spec §2)
- **Default sort `-price`.** Skin names and rarity names stay English; taxonomy (category, weapon, wear, StatTrak/Souvenir) is localised. (spec §2, §11)
- **Pricing seed = YuPay's tuned `DEFAULT_RULES`** (min margin $0.03, floor $0.10, retail brackets 10 % → 5 % → 7 % → 3 % → 2 %), stored prices recomputed after every price tick; the admin pricing editor is M4. (spec §2, §9)
- **Money:** `Decimal` / strings on the wire, never floats; Waxpeer units 1000 = $1; USD with 2 decimals for sell prices; soʻm rounded **up** to `uzs_round_to` (100). (spec §5, §13)
- **Images:** ByMykel Steam CDN URLs stored as is; the API rewrites the host to `CSMARKET_SKINS_IMAGE_HOST` (`community.fastly.steamstatic.com`); cards `/256fx256f`, item page `/512fx384f`, thumbs `/128fx96f`. (spec §8)
- **Live listings** (`GET /skins/{slug}/listings`): Waxpeer search-by-name on a cache miss only — 90 s fresh / 1 h stale, process-wide budget 18/min (under Waxpeer's 20/min), 2-min breaker, degrades to the 5-min snapshot with `degraded: true`, own `ip_guard` bucket `skins-listings`, 4 s timeout. The carve-out is already in AGENTS §11. (spec §7.3)
- **SEO:** unknown slug / category / weapon = **real HTTP 404** (no `loading.tsx` above those pages; existence checked before any Suspense); an API outage is an error, never a 404; RU titles/H1 say «КС2» with «(CS2)» beside, UZ hub title carries «CS2 skins», EN H1 «CS2 skins»; sitemap index `/sitemap.xml` → `/skins-sitemap/<n>.xml` (5 000 items × 3 locales) + `/skins-sitemap/landings.xml`. (spec §10)
- **Copy (owner):** short sentences; outcome, not mechanism; no service meta («цены обновляются каждые 5 минут»); concrete («в Узбекистане»); «вы»; never «всегда дешевле»; «Мгновенная доставка» is acceptable. UZ text uses ʻ (U+02BB) in Oʻzbekiston, soʻm, qoʻl…, never ASCII `'`. (spec §11, AGENTS §12)
- **Locales ru / uz / en**, every key in all three in the same task (parity test). (AGENTS §12)
- **Never log PII** (Steam ID, email, IP, trade-link token); Waxpeer's API key rides the query string, so never log a Waxpeer URL or httpx exception text — log method, path, status, exception type name. (AGENTS §10)
- **Idempotency:** every state-changing endpoint accepts `Idempotency-Key` (≥ 16 chars) through `core.idempotency`. (AGENTS §10)
- **Admin actions are audited** in `admin_audit_log` (spec §5, §13); payloads carry no PII.
- **Scheduler jobs only time work** (`register(scheduler)`, `first_run_after(n)` staggered ≥ 15 s); logic lives in a module's service. (AGENTS §4)
- **Forbidden tokens** in `apps/*/src`, `packages/*/src`: `yupay`, `sku`, `brand_`, `supplier`, `guest_email`, `fulfiller`, `merchants`, `merchant_api`, `voucher`, `game_id`. YuPay comments that say "supplier" become "Waxpeer". (AGENTS §6)
- **Dev ports** api 8100, web 3100, admin 3102; never touch `yupay*` containers or unnamed testcontainers you did not start; kill processes by PID only. (AGENTS §13, §14)
- **Routers mount in `apps/api/src/csmarket/api/v1/router.py`** from each module's `routes.py` (import-cycle rule from M1, guarded by `tests/unit/test_import_order.py`). Every route change regenerates `docs/api/openapi.json` in the same commit (`cd apps/api && uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json`).
- **Commits:** Conventional Commits, scope `api/skins`, `api/fx`, `api/admin`, `scheduler`, `packages/utils`, `web/catalogue`, `web/item`, `web/seo`, `admin/catalogue`, `e2e`, `docs`; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never push.

## Rulings taken while planning (owner may veto)

- **Q1 — No public feature flag.** YuPay's `cs2_skins_enabled` 404'd the skins API; here skins _are_ the product, so the read API is always on. `CSMARKET_SKINS_SYNC_ENABLED` (default `false`, `true` in prod secrets) gates only the scheduler's ByMykel import and Waxpeer price sync. `CSMARKET_SKINS_CATEGORIES` keeps YuPay's allow-list of visible categories.
- **Q2 — Pricing drops the B2B channel.** YuPay's `PricingRules.b2b` and `quote(extra_pp=…)` exist for its merchant API; csmarket has none. Retail brackets, expenses, liquidity, category/weapon pp, min margin, floor, rounding and Steam cap stay exactly as YuPay's.
- **Q3 — `fx` is new and small, not YuPay's port.** YuPay has no CBU provider and a 2 600-line multi-provider fx. Here: `fx_snapshots` (spec §5 columns) + CBU fetch (`https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/`) + Redis `fx:usd_uzs` + `current_usd_uzs()`; an hourly scheduler job inserts a snapshot when the rate changed or the last one is older than 20 h; a snapshot older than 7 days counts as no rate. Without a rate, prices fall back to USD on the page and soʻm filters are ignored (YuPay behaviour). M4 orders reference `fx_snapshots.id`.
- **Q4 — Hide an item** = new column `skin_items.hidden bool not null default false`. A hidden item disappears from the catalogue, facets, suggest, sitemap slugs and family lists, and `GET /skins/{slug}` answers 404; the price sync still prices it, so unhiding is instant. Not in YuPay.
- **Q5 — `admin_audit_log` arrives in M2** (M1's P5 put it with "the first admin action" — hiding an item and editing aliases are that action). Spec §5 columns exactly; written by `admin.audit.record()`; no audit UI yet.
- **Q6 — Job status** lives in Redis `skins:job:{import|price_sync}` (JSON: finished_at, ok, counters, error kind; no TTL), written by the scheduler jobs, read by the admin status endpoint. No new table, no "run now" button (a runbook command does that).
- **Q7 — Dev and e2e data without Waxpeer.** The Waxpeer key works only from the prod IP, so `python -m csmarket.scripts.seed_skins_dev` (refuses in prod) loads a committed ByMykel-shaped fixture of ~60 items, gives them deterministic fake snapshot prices through the real `apply_prices` + `reprice_rows`, and writes a `source='dev'` fx snapshot at 12 700 soʻm if none exists. `make seed-skins`.
- **Q8 — Shared TS lives in `@csmarket/utils`**: YuPay keeps the skins query model, URL serialiser, view helpers and JSON-LD serializer in `packages/utils`; they move to `packages/utils/src/skins/*` here (AGENTS §4: shared TS utility).
- **Q9 — Indexability rule on `/`.** Any _recognised filter_ param (category, weapon, exterior, rarity, team, stattrak, q, min, max, sort, cursor) makes the page `noindex,follow` with canonical `/`; unknown params (utm_*, fbclid, gclid) do not. YuPay noindexed on any param, which would hide every tracked visit to the home page.
- **Q10 — Outage is not a 404.** Web data helpers return `null` only on an API 404 and throw otherwise (YuPay's facets helper swallowed errors into a 404). The home page never calls `notFound()`.
- **Q11 — Sitemap alternates include `x-default` → ru**, matching the pages' `<link rel="alternate">` (YuPay's sitemap omitted it).
- **Q12 — JSON-LD:** Product with a single `Offer` in UZS (YuPay's code, not its README's AggregateOffer), only when a soʻm price exists; BreadcrumbList; FAQPage.
- **Q13 — Search aliases are admin-edited, none seeded.** Admin can add «ак» → «ak-47» and the like; there is no seed list in M2.

## Review Focus

1. **A wrong slug must return HTTP 404, not a 200 page.** `/item/no-such-skin`, `/category/xyz`, `/weapon/xyz` and a hidden item → status 404 in a production build. → Task 14 / Task 15 route tests + Task 17 e2e `expect(response.status()).toBe(404)`.
2. **No rate, no Waxpeer, no Redis must still render the catalogue.** FX unavailable → prices in USD, soʻm filter ignored; Waxpeer key absent / breaker open → listings degraded to the snapshot; Redis down → reads fall through to Postgres. → Task 7 `test_catalog_without_fx_shows_usd_and_ignores_uzs_bounds`, Task 8 `test_listings_degrade_without_key`, Task 7 `test_catalog_survives_redis_down`.
3. **A broken or partial Waxpeer snapshot must not wipe the catalogue.** A snapshot naming fewer than half the active items, a 429, missing CSV columns → the tick is refused and nothing goes inactive. → Task 6 `test_sync_refuses_a_thin_snapshot` (ported) + Task 4 contract tests.
4. **A hidden item vanishes everywhere and comes back on unhide.** Catalogue, facets counts, suggest, sitemap slugs, family, detail (404) — and all return after unhide, without waiting for the 60 s page cache. → Task 9 `test_hide_hides_everywhere_and_unhide_restores`.
5. **Tracking params keep the home page indexable.** `/?utm_source=x` → `index`, canonical `/`; `/?category=knives` → `noindex,follow`. → Task 13 `metadata.test.ts`.

---

## File structure (what M2 creates or changes)

```
apps/api/src/csmarket/
├── core/config.py                         + skins_*, bymykel, fx_*, waxpeer timeout, "skins-listings" bucket
├── modules/skins/
│   ├── models.py naming.py slugs.py taxonomy.py images.py           (T1, ported)
│   ├── pricing.py repricing.py settings.py                           (T2, ported, B2B dropped)
│   ├── waxpeer.py                                                    (T4, + snapshot / prices / search)
│   ├── bymykel.py job_status.py                                      (T5)
│   ├── cachekeys.py prices.py                                        (T6)
│   ├── service.py schemas.py routes.py seo_routes.py                 (T7)
│   ├── listings.py                                                   (T8)
│   ├── admin_routes.py admin_schemas.py                              (T9)
│   ├── api.py README.md
├── modules/fx/{__init__,api,models,cbu,service}.py + README.md       (T3, new)
├── modules/admin/{models,audit}.py                                   (T9, new)
├── scripts/seed_skins_dev.py + scripts/dev_skins/{skins,agents,crates}.json   (T10)
├── api/v1/router.py                                                  (mounts)
apps/api/migrations/versions/0003_skins_catalog.py 0004_fx_snapshots.py 0005_admin_audit_log.py
apps/api/tests/{unit,integration,contract}/test_skins_*.py test_fx_*.py + tests/fixtures/skins/*
apps/scheduler/src/csmarket_scheduler/jobs/{fx_refresh,skins_catalog_import,skins_price_sync}.py
packages/utils/src/skins/{query,view,float,json-ld,money}.ts (+ tests)                (T11)
packages/i18n/locales/{ru,uz,en}/web.json                       + web.skins.*          (T12)
apps/web/public/skins/categories/*.png                                                  (T12)
apps/web/src/lib/{server-api,skins,paths,seo,skin-seo,skin-landing,skins-sitemap}.ts   (T12–T15)
apps/web/src/components/{JsonLd.tsx, skins/*.tsx}                                       (T13–T15)
apps/web/src/app/[locale]/{page.tsx, item/[slug]/page.tsx, category/[category]/page.tsx,
                           weapon/[weapon]/page.tsx}
apps/web/src/app/{sitemap.xml/route.ts, skins-sitemap/[file]/route.ts, robots.txt/route.ts}
apps/admin/src/features/catalogue/*                                                     (T16)
e2e/tests/catalogue.spec.ts e2e/tests/admin-catalogue.spec.ts                           (T17)
docs/: decisions/0005-skins-catalogue-fx-and-indexing.md, architecture/{module-map,cache-keys,
       sequence-diagrams/skins-price-sync.mmd}, runbooks/skins-catalogue.md,
       product/flows/skins-browse.md, api/README.md, security/pii-handling.md       (T18)
```

---

### Task 1: Settings, `skin_*` tables (migration 0003) and the pure naming modules

**Files:**

- Modify: `apps/api/src/csmarket/core/config.py`, `.env.example`, `apps/api/.env.example`, `infra/secrets-example/api.env`, `docker-compose.yml` (`x-app-env`), `apps/api/migrations/env.py`, `apps/api/tests/integration/conftest.py` (`_EMPTY_IN_ORDER`), `apps/api/tests/unit/test_config.py`
- Create: `apps/api/src/csmarket/modules/skins/{models,naming,slugs,taxonomy,images}.py`, `apps/api/migrations/versions/0003_skins_catalog.py`
- Test: `apps/api/tests/unit/test_skins_naming.py`, `apps/api/tests/unit/test_skins_images.py`, `apps/api/tests/unit/test_skins_slugs.py`, `apps/api/tests/integration/test_skins_models.py`

**Interfaces:**

- Produces:
  - `Settings` fields: `skins_sync_enabled: bool = False`, `skins_categories: str = "rifles,pistols,smgs,heavy,knives,gloves,agents,cases,keys,music-kits,charms"`, `skins_image_host: str = "community.fastly.steamstatic.com"`, `bymykel_base_url: str = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en"`, `skins_import_interval_hours: int = 24` (ge 1), `skins_snapshot_interval_minutes: int = 5` (ge 1), `skins_listings_budget_per_minute: int = 18` (ge 0), `skins_listings_timeout_seconds: float = 4.0`, `waxpeer_request_timeout_seconds: float = 20.0`, `fx_cbu_url: str = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/"`, `fx_timeout_seconds: float = 5.0`, `fx_refresh_interval_minutes: int = 60` (ge 5), `fx_max_age_days: int = 7` (ge 1); `auth_ip_guard_bucket_max` default gains `"skins-listings": 60`.
  - `skins.models`: `SkinItem`, `SkinPricingRules`, `SkinSearchAlias` (columns below).
  - `skins.naming`: `EXTERIOR_CODES`, `PHASES`, `ParsedName`, `canonical_name(raw) -> tuple[str, str]`, `parse_market_name(raw) -> ParsedName`, `slug_for(market_hash_name, phase) -> str`, `search_text(market_hash_name, phase) -> str`.
  - `skins.slugs`: `suffixed(slug, key) -> str`, `resolve(wanted, existing) -> dict[tuple[str, str], str]`, `async existing_slugs(db) -> set[str]`.
  - `skins.taxonomy`: `CATEGORY_SLUGS`, `FILE_CATEGORIES`, `category_for_skin(entry, parsed) -> str`, `category_for_file(file_key) -> str`, `category_for_waxpeer_type(type_name) -> str`.
  - `skins.images`: `steam_image(url: str | None, *, host: str) -> str | None`.

- [ ] **Step 1: Settings (failing test first)**

Append to `apps/api/tests/unit/test_config.py`:

```python
def test_skins_and_fx_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.skins_sync_enabled is False
    assert s.skins_categories.split(",")[:3] == ["rifles", "pistols", "smgs"]
    assert s.skins_image_host == "community.fastly.steamstatic.com"
    assert s.bymykel_base_url.endswith("/ByMykel/CSGO-API/main/public/api/en")
    assert (s.skins_import_interval_hours, s.skins_snapshot_interval_minutes) == (24, 5)
    assert (s.skins_listings_budget_per_minute, s.skins_listings_timeout_seconds) == (18, 4.0)
    assert s.waxpeer_request_timeout_seconds == 20.0
    assert s.fx_cbu_url == "https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/"
    assert (s.fx_refresh_interval_minutes, s.fx_max_age_days) == (60, 7)
    assert s.auth_ip_guard_bucket_max["skins-listings"] == 60
```

(Match the file's existing construction idiom if it differs from `_env_file=None` — e.g. the M1 tests clear `CSMARKET_*` env with `monkeypatch`; reuse it.)

Run: `cd apps/api && uv run pytest tests/unit/test_config.py -k skins -q` → FAIL (unknown attribute).

Add the fields to `Settings` in `core/config.py` in a `# --- skins (M2) ---` and `# --- fx (M2) ---` block, each with a one-line `description`, `Field(ge=…)` bounds as listed; add `"skins-listings": 60` to the `auth_ip_guard_bucket_max` default dict. Env files: `.env.example` and `apps/api/.env.example` get `CSMARKET_SKINS_SYNC_ENABLED=false` with the comment "true only where the Waxpeer key works (prod); the import alone also runs in dev"; `infra/secrets-example/api.env` gets `CSMARKET_SKINS_SYNC_ENABLED=true`; `docker-compose.yml` `x-app-env` gets `CSMARKET_SKINS_SYNC_ENABLED: ${CSMARKET_SKINS_SYNC_ENABLED:-false}`. Re-run → PASS.

- [ ] **Step 2: Pure modules — port with tests**

Copy through the filter, no logic change:

```bash
for f in naming slugs taxonomy images; do
  sed -f scripts/port-rename.sed /Users/macbook_uz/Projects/yupay/apps/api/src/yupay/modules/skins/$f.py \
    > apps/api/src/csmarket/modules/skins/$f.py
done
for t in test_skins_naming test_skins_images; do
  sed -f scripts/port-rename.sed /Users/macbook_uz/Projects/yupay/apps/api/tests/unit/$t.py \
    > apps/api/tests/unit/$t.py
done
```

Deltas: logger names `csmarket.skins.*`; nothing else should differ (grep the result for `yupay`, `supplier`, `sku` — reword any such comment to "Waxpeer"). `slugs.py` imports `SkinItem` from Step 3's models, so write models first if you run the slugs test before Step 3.

Write `apps/api/tests/unit/test_skins_slugs.py` (YuPay has no dedicated file):

```python
from csmarket.modules.skins.slugs import resolve, suffixed


def test_free_slug_is_kept() -> None:
    assert resolve({("AK-47 | Redline (Field-Tested)", ""): "ak-47-redline-field-tested"}, set()) == {
        ("AK-47 | Redline (Field-Tested)", ""): "ak-47-redline-field-tested"
    }


def test_colliding_slug_gets_a_stable_hex_suffix() -> None:
    key = ("★ Karambit | Doppler (Factory New)", "Phase 2")
    taken = {"karambit-doppler-factory-new-phase-2"}
    out = resolve({key: "karambit-doppler-factory-new-phase-2"}, taken)
    assert out[key] != "karambit-doppler-factory-new-phase-2"
    assert out[key] == suffixed("karambit-doppler-factory-new-phase-2", key)
    assert out[key] == resolve({key: "karambit-doppler-factory-new-phase-2"}, taken)[key]


def test_two_new_rows_wanting_one_slug_both_get_distinct_slugs() -> None:
    a, b = ("A", ""), ("B", "")
    out = resolve({a: "same", b: "same"}, set())
    assert len(set(out.values())) == 2
```

(If `resolve`'s real signature differs — read `yupay-skins:slugs.py:29` — keep the assertions' intent: a free slug stays, a taken slug gets the deterministic `suffixed` form, two newcomers never share a slug.)

- [ ] **Step 3: Models + migration 0003 (failing integration test first)**

Port `yupay-skins:models.py` keeping **only** `SkinItem`, `SkinPricingRules`, `SkinSearchAlias` (drop `SkinTrade`, `SkinTradeLink` and their imports). Deltas:

- `SkinItem` gains `team: Mapped[str | None] = mapped_column(String(2))` (YuPay added it in 0091 — check the YuPay model already has it; it does), `sell_price_usd Numeric(12,2) NULL`, `discount_percent Integer NULL` (0088 — present in the model), and the **new** `hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)` with a docstring line: "Admin hid it: off every public read, priced as usual (ruling Q4)."
- `SkinPricingRules.updated_by` FK → `users.id` `ON DELETE SET NULL` (csmarket's `users` exists since M1).
- Imports from `csmarket.core.db`.

Migration `0003_skins_catalog.py` (`down_revision = "0002_users_auth"`): one migration = YuPay 0087 + 0088 + 0091 collapsed, plus `hidden`. `pg_trgm` already exists (0001 creates it) — do not create it again. Tables, exactly the model:

- `skin_items` columns as `models.SkinItem` (id uuid pk; market_hash_name varchar(255); phase varchar(16) not null default ''; slug varchar(255); category varchar(32); weapon varchar(64); skin varchar(128); exterior varchar(2); stattrak/souvenir bool not null default false; rarity varchar(64); rarity_color varchar(9); image_url text; min_float/max_float numeric(6,5); paint_index int; team varchar(2); source varchar(16) not null default 'stub'; search_text text not null; steam_price_units bigint; min_auto_units bigint; count_auto int not null default 0; cheapest_auto jsonb not null default '[]'; min_all_units bigint; count_all int not null default 0; price_hash varchar(40); prices_updated_at timestamptz; active bool not null default false; hidden bool not null default false; margin_override_pp numeric(6,2); fixed_price_usd numeric(12,2); sell_price_usd numeric(12,2); discount_percent int; created_at/updated_at timestamptz not null default now()).
- Constraints `uq_skin_items_name_phase (market_hash_name, phase)`, `uq_skin_items_slug (slug)`; indexes `ix_skin_items_category_price (category, min_auto_units)`, `ix_skin_items_weapon (weapon)`, `ix_skin_items_active (active)`, `ix_skin_items_category_sell (category, sell_price_usd)`, `ix_skin_items_discount (discount_percent)`, `ix_skin_items_search_trgm` GIN `(search_text gin_trgm_ops)` (`postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"}`).
- `skin_pricing_rules (id int pk, rules jsonb not null, updated_by uuid null fk users.id on delete set null, updated_at timestamptz not null default now(), CHECK (id = 1) named ck_skin_pricing_rules_singleton)`. No seed row.
- `skin_search_aliases (alias varchar(64) pk, text varchar(128) not null)`.
- `downgrade()` drops the three tables (aliases, rules, items).

`apps/api/migrations/env.py`: import `csmarket.modules.skins.models`. Integration conftest: `_EMPTY_IN_ORDER = ("idempotent_responses", "refresh_tokens", "skin_pricing_rules", "skin_search_aliases", "skin_items", "users")` (rules reference users → before users).

Port `yupay:apps/api/tests/integration/test_skins_models.py` through the filter (it inserts a row, checks the unique constraints and defaults); add:

```python
async def test_hidden_defaults_to_false(db_session: AsyncSession) -> None:
    item = SkinItem(
        id=new_id(), market_hash_name="AK-47 | Redline (Field-Tested)", phase="",
        slug="ak-47-redline-field-tested", category="rifles", search_text="ak 47 redline field tested",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    assert item.hidden is False and item.active is False and item.cheapest_auto == []
```

Run: `cd apps/api && uv run pytest tests/integration/test_skins_models.py -q` → FAIL first (no table), PASS after the migration. Also `uv run pytest tests/integration/test_migrations.py -q` (head matches models — M0/M1 test).

- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_skins_naming.py tests/unit/test_skins_images.py tests/unit/test_skins_slugs.py tests/integration/test_skins_models.py tests/integration/test_migrations.py tests/unit/test_config.py -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/skins): catalogue tables, naming and taxonomy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Pricing rules, `quote()`, stored-price repricing (B2B dropped)

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/{pricing,repricing,settings}.py`
- Test: `apps/api/tests/unit/test_skins_pricing.py`, `apps/api/tests/unit/test_skins_pricing_props.py` (hypothesis), `apps/api/tests/integration/test_skins_reprice.py`

**Interfaces:**

- Consumes: `SkinItem`, `SkinPricingRules` (Task 1), `core.redis.get_redis`, `core.config.Settings`.
- Produces:
  - `skins.pricing`: `Bracket`, `LiquidityBand`, `PricingRules` (fields: `expenses_percent`, `retail`, `liquidity`, `category_pp`, `weapon_pp`, `min_margin_usd`, `price_floor_usd`, `uzs_round_to`, `cap_at_steam` — **no `b2b`**), `DEFAULT_RULES`, `Quote`, `Applied`, `bracket_margin`, `liquidity_pp`, `quote(cost_units, *, rules, category, weapon=None, count_auto=None, item_pp=None, fixed_price_usd=None, steam_price_units=None) -> Quote`, `to_uzs(price_usd, rate, *, round_to) -> Decimal`.
  - `skins.repricing`: `PRICING_LOCK_KEY`, `async lock_pricing(db)`, `discount_of(price, steam_price_units) -> int | None`, `async reprice_rows(db, rules, *, ids=None) -> int`.
  - `skins.settings`: `async load_rules(db, *, fresh=False) -> PricingRules`, `async save_rules(db, *, rules, admin_id)`, `async publish_rules(rules)`, `enabled_categories(settings) -> list[str]`; Redis key `skins:pricing` (TTL 3600).

- [ ] **Step 1: Port `pricing.py` with the B2B deltas**

`sed -f scripts/port-rename.sed yupay-skins:pricing.py > apps/api/src/csmarket/modules/skins/pricing.py`, then:

- Delete `Channel` (and from `__all__`), the `b2b` field, the `b2b` list in `DEFAULT_RULES`, the `channel` and `extra_pp` parameters of `quote()` and their use (`brackets = rules.retail`; the pp sum has no `extra_pp`).
- `_shape` validates only `retail`: `brackets = self.retail` with the same two checks and messages prefixed `retail:`.
- Docstring of `quote()` drops the "per-merchant" sentence; module docstring says "the brackets" not "brackets per channel".
- Keep every other number and comment of `DEFAULT_RULES` verbatim (they are owner decisions).

- [ ] **Step 2: Port the pricing tests, add properties**

`sed -f scripts/port-rename.sed yupay:apps/api/tests/unit/test_skins_pricing.py > apps/api/tests/unit/test_skins_pricing.py`; delete the tests that exercise `b2b`/`channel`/`extra_pp` (grep them) and any `b2b=` keyword in rule fixtures. An old document that still carries a `b2b` key must keep loading (Pydantic's default `extra="ignore"` does that; the test pins it):

```python
def test_a_document_with_a_b2b_key_still_loads() -> None:
    doc = DEFAULT_RULES.model_dump(mode="json") | {"b2b": [{"from_usd": "0", "percent": "6"}]}
    assert PricingRules.model_validate(doc).retail == DEFAULT_RULES.retail
```

`apps/api/tests/unit/test_skins_pricing_props.py` (spec §14: hypothesis on pricing):

```python
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from csmarket.modules.skins.pricing import DEFAULT_RULES, quote, to_uzs

costs = st.integers(min_value=1, max_value=50_000_000)  # $0.001 .. $50 000
counts = st.one_of(st.none(), st.integers(min_value=0, max_value=5000))
cats = st.sampled_from(["rifles", "knives", "stickers", "cases"])


@given(cost=costs, count=counts, cat=cats)
def test_price_covers_cost_plus_min_margin_and_floor(cost: int, count: int | None, cat: str) -> None:
    q = quote(cost, rules=DEFAULT_RULES, category=cat, count_auto=count)
    assert q.price_usd >= q.cost_usd + DEFAULT_RULES.min_margin_usd - Decimal("0.01")
    assert q.price_usd >= DEFAULT_RULES.price_floor_usd
    assert q.price_usd == q.price_usd.quantize(Decimal("0.01"))


@given(a=costs, b=costs, count=counts)
def test_price_never_falls_when_cost_rises(a: int, b: int, count: int | None) -> None:
    lo, hi = sorted((a, b))
    p_lo = quote(lo, rules=DEFAULT_RULES, category="rifles", count_auto=count).price_usd
    p_hi = quote(hi, rules=DEFAULT_RULES, category="rifles", count_auto=count).price_usd
    assert p_hi >= p_lo


@given(usd=st.decimals(min_value=Decimal("0.10"), max_value=Decimal("100000"), places=2),
       rate=st.decimals(min_value=Decimal("8000"), max_value=Decimal("20000"), places=4))
def test_uzs_rounds_up_to_a_hundred(usd: Decimal, rate: Decimal) -> None:
    uzs = to_uzs(usd, rate, round_to=100)
    assert uzs % 100 == 0 and uzs >= usd * rate and uzs - usd * rate < 100
```

(If `min_margin` interacts with the floor so the first assertion needs `max(...)`, keep the property "never below cost + min margin, never below the floor" and adjust the expression, not the property.)

Run: `uv run pytest tests/unit/test_skins_pricing.py tests/unit/test_skins_pricing_props.py -q` → PASS.

- [ ] **Step 3: Port `repricing.py` and `settings.py`**

Both through the filter. `repricing.py`: no deltas besides imports (`quote()` calls drop nothing — they never passed `channel`). `settings.py`:

- `enabled_categories(settings)` reads `settings.skins_categories` (was `cs2_skins_categories`).
- Docstring: drop the "Same contract as `gifts.settings`" sentence; say "A save touches Postgres only; the caller publishes to Redis after its own commit."
- Logger `csmarket.skins.settings`; Redis key stays `skins:pricing`.

`reprice_rows` must also treat **hidden** rows as priceable — it already reprices every active row; `hidden` is not consulted (ruling Q4). Add a one-line comment saying so.

Port `yupay:apps/api/tests/integration/test_skins_sell_price.py` → `apps/api/tests/integration/test_skins_reprice.py`, keeping only the tests about `reprice_rows`/`discount_of`/`load_rules` (drop route assertions and any fx manual-override setup — those return in Task 7). Add:

```python
async def test_hidden_rows_are_repriced_too(db_session: AsyncSession) -> None:
    item = await _active_item(db_session, min_auto_units=10_000, hidden=True)  # helper from the ported file
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.refresh(item)
    assert item.sell_price_usd is not None
```

(`_active_item` = the ported file's row factory; add a `hidden` kwarg if it lacks one.)

- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_skins_pricing.py tests/unit/test_skins_pricing_props.py tests/integration/test_skins_reprice.py -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/skins): pricing rules, quote and stored sell prices

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `fx` — CBU USD/UZS rate, `fx_snapshots`, refresh job

**Files:**

- Create: `apps/api/src/csmarket/modules/fx/{__init__,api,models,cbu,service}.py`, `modules/fx/README.md`, `apps/api/migrations/versions/0004_fx_snapshots.py`, `apps/scheduler/src/csmarket_scheduler/jobs/fx_refresh.py`
- Modify: `apps/api/migrations/env.py`, `apps/api/tests/integration/conftest.py` (`_EMPTY_IN_ORDER` + `"fx_snapshots"` first), `apps/scheduler/src/csmarket_scheduler/main.py` (register + import fx models), `apps/scheduler/src/csmarket_scheduler/jobs/__init__.py`, `apps/scheduler/tests/test_main.py`
- Test: `apps/api/tests/contract/test_cbu_rate.py`, `apps/api/tests/integration/test_fx_service.py`, `apps/scheduler/tests/test_fx_refresh.py`

**Interfaces:**

- Consumes: `core.db`, `core.redis.get_redis`, `core.clock.now`, `core.ids.new_id`, `Settings.fx_*`.
- Produces:
  - `fx.models.FxSnapshot` — table `fx_snapshots (id uuid pk, usd_uzs numeric(12,4) not null CHECK > 0, source varchar(16) not null, fetched_at timestamptz not null default now())`, index `ix_fx_snapshots_fetched_at (fetched_at)`.
  - `fx.cbu`: `CbuError(Exception)`, `async fetch_usd_uzs(*, url: str, timeout: float, client: httpx.AsyncClient | None = None) -> Decimal`.
  - `fx.service`: `UsdUzs(rate: Decimal, snapshot_id: str, fetched_at: datetime, source: str)` (frozen dataclass), `REDIS_KEY = "fx:usd_uzs"`, `async current_usd_uzs(db, redis, *, max_age_days: int) -> UsdUzs | None`, `async refresh_usd_uzs(db, redis, *, fetch: Callable[[], Awaitable[Decimal]], source: str = "cbu") -> UsdUzs`, `async record_snapshot(db, *, rate, source) -> FxSnapshot`.
  - `fx.api` re-exports `FxSnapshot`, `UsdUzs`, `current_usd_uzs`, `refresh_usd_uzs`, `record_snapshot`, `fetch_usd_uzs`, `CbuError`.
  - Scheduler job `fx.refresh` (interval `fx_refresh_interval_minutes`, first run `first_run_after(20)`).

- [ ] **Step 1: CBU fetch (contract test first)**

The public endpoint `GET https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/` answers a JSON **list** with one object. Shape (as published by cbu.uz; values made up):

```json
[
  {
    "id": 69,
    "Code": "840",
    "Ccy": "USD",
    "CcyNm_RU": "Доллар США",
    "CcyNm_UZ": "AQSH dollari",
    "CcyNm_UZC": "АҚШ доллари",
    "CcyNm_EN": "US Dollar",
    "Nominal": "1",
    "Rate": "12688.45",
    "Diff": "-4.12",
    "Date": "30.09.2026"
  }
]
```

```python
# apps/api/tests/contract/test_cbu_rate.py
from decimal import Decimal

import httpx
import pytest
import respx

from csmarket.modules.fx.cbu import CbuError, fetch_usd_uzs

URL = "https://cbu.test/ru/arkhiv-kursov-valyut/json/USD/"
ROW = {"Ccy": "USD", "Nominal": "1", "Rate": "12688.45", "Date": "30.09.2026"}


@respx.mock
async def test_reads_the_rate() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[ROW]))
    assert await fetch_usd_uzs(url=URL, timeout=5) == Decimal("12688.45")


@respx.mock
async def test_nominal_divides() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[ROW | {"Nominal": "10", "Rate": "126884.5"}]))
    assert await fetch_usd_uzs(url=URL, timeout=5) == Decimal("12688.45")


@pytest.mark.parametrize(
    "body",
    [[], {}, [ROW | {"Ccy": "EUR"}], [ROW | {"Rate": "abc"}], [ROW | {"Rate": "0"}], [ROW | {"Rate": "999"}], [ROW | {"Rate": "100001"}], "<html>"],
)
@respx.mock
async def test_refuses_what_is_not_a_plausible_usd_rate(body: object) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(CbuError):
        await fetch_usd_uzs(url=URL, timeout=5)


@respx.mock
async def test_http_and_network_errors_are_cbu_errors() -> None:
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(CbuError):
        await fetch_usd_uzs(url=URL, timeout=5)
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(CbuError):
        await fetch_usd_uzs(url=URL, timeout=5)
```

```python
# apps/api/src/csmarket/modules/fx/cbu.py
"""The Central Bank of Uzbekistan's official USD rate (spec §9: the sell rate).

One public, keyless JSON endpoint. Anything that is not one plausible USD row is an
error — a wrong rate prices the whole catalogue, so we refuse rather than guess.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from csmarket.core.logging import get_logger

log = get_logger("csmarket.fx.cbu")

#: Soʻm per dollar outside this band is a parsing error, not a market move.
_PLAUSIBLE = (Decimal(1000), Decimal(100000))


class CbuError(Exception):
    """The CBU answer was missing, unreachable or implausible."""


async def fetch_usd_uzs(
    *, url: str, timeout: float, client: httpx.AsyncClient | None = None
) -> Decimal:
    """Soʻm per one US dollar, as the CBU publishes it today.

    Raises:
        CbuError: Network failure, HTTP error, or an answer that is not one plausible USD row.
    """
    try:
        if client is not None:
            resp = await client.get(url, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as own:
                resp = await own.get(url)
    except httpx.HTTPError as exc:
        log.warning("fx.cbu.network_error", error=type(exc).__name__)
        raise CbuError(type(exc).__name__) from exc
    if resp.status_code != 200:
        raise CbuError(f"status {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise CbuError("not json") from exc
    if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], dict):
        raise CbuError("unexpected shape")
    row = body[0]
    if row.get("Ccy") != "USD":
        raise CbuError("not the USD row")
    try:
        rate = Decimal(str(row["Rate"])) / Decimal(str(row.get("Nominal") or "1"))
    except (KeyError, InvalidOperation, ZeroDivisionError) as exc:
        raise CbuError("bad rate") from exc
    if not _PLAUSIBLE[0] <= rate <= _PLAUSIBLE[1]:
        raise CbuError("implausible rate")
    return rate.quantize(Decimal("0.0001"))
```

- [ ] **Step 2: Model, migration 0004, service (integration test first)**

```python
# apps/api/tests/integration/test_fx_service.py
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core import clock
from csmarket.core.redis import get_redis
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.fx.service import REDIS_KEY, current_usd_uzs, record_snapshot, refresh_usd_uzs


async def _fetch_12700() -> Decimal:
    return Decimal("12700")


async def test_no_snapshot_means_no_rate(db_session: AsyncSession) -> None:
    assert await current_usd_uzs(db_session, get_redis(), max_age_days=7) is None


async def test_refresh_records_and_caches(db_session: AsyncSession) -> None:
    got = await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    await db_session.commit()
    assert got.rate == Decimal("12700") and got.source == "cbu"
    assert await get_redis().get(REDIS_KEY) is not None
    again = await current_usd_uzs(db_session, get_redis(), max_age_days=7)
    assert again is not None and again.snapshot_id == got.snapshot_id


async def test_same_rate_within_20h_does_not_add_a_row(db_session: AsyncSession) -> None:
    await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(FxSnapshot)) == 1


async def test_a_changed_rate_adds_a_row(db_session: AsyncSession) -> None:
    await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)

    async def _fetch_12750() -> Decimal:
        return Decimal("12750")

    got = await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12750)
    await db_session.commit()
    assert got.rate == Decimal("12750")
    assert await db_session.scalar(select(func.count()).select_from(FxSnapshot)) == 2


async def test_redis_down_falls_back_to_postgres(db_session: AsyncSession, monkeypatch) -> None:
    await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
    await db_session.commit()

    class Broken:
        async def get(self, *_a: object) -> None:
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("down")

        async def set(self, *_a: object, **_k: object) -> None:
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("down")

    got = await current_usd_uzs(db_session, Broken(), max_age_days=7)  # type: ignore[arg-type]
    assert got is not None and got.rate == Decimal("12700")


async def test_a_week_old_snapshot_is_no_rate(db_session: AsyncSession) -> None:
    base = clock.now()
    clock.set_clock(lambda: base - timedelta(days=8))
    try:
        await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
        await db_session.commit()
    finally:
        clock.reset_clock()
    assert await current_usd_uzs(db_session, get_redis(), max_age_days=7) is None
```

(`record_snapshot` must set `fetched_at=now()` from `core.clock` explicitly, not rely on the server default, so the clock override works.)

`fx/models.py`:

```python
"""``fx_snapshots`` — every CBU USD/UZS rate we priced with (spec §5)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base


class FxSnapshot(Base):
    """One rate as fetched. Orders (M4) point at the row they were priced with."""

    __tablename__ = "fx_snapshots"
    __table_args__ = (
        CheckConstraint("usd_uzs > 0", name="usd_uzs_positive"),
        Index("ix_fx_snapshots_fetched_at", "fetched_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    usd_uzs: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

Migration `0004_fx_snapshots.py` (`down_revision = "0003_skins_catalog"`) creates exactly that (the check constraint becomes `ck_fx_snapshots_usd_uzs_positive` through the naming convention). `migrations/env.py` imports `csmarket.modules.fx.models`; `_EMPTY_IN_ORDER` gets `"fx_snapshots"` (no FKs; anywhere is fine — put it first).

`fx/service.py`:

```python
"""The USD/UZS rate the catalogue prices with (ruling Q3).

Postgres (``fx_snapshots``) is the record; Redis ``fx:usd_uzs`` is a copy the request
path reads first. A Redis error is never fatal — the newest snapshot is one indexed
query away. A rate older than ``max_age_days`` is treated as no rate: the page then
shows dollars rather than soʻm at a week-old rate.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.modules.fx.models import FxSnapshot

log = get_logger("csmarket.fx.service")

REDIS_KEY = "fx:usd_uzs"
_REDIS_TTL_SECONDS = 86_400
#: A refresh with an unchanged rate adds a row only when the newest is this old.
_REFRESH_ROW_AFTER = timedelta(hours=20)


@dataclass(frozen=True)
class UsdUzs:
    """A rate and the snapshot it came from."""

    rate: Decimal
    snapshot_id: str
    fetched_at: datetime
    source: str


def _of(row: FxSnapshot) -> UsdUzs:
    return UsdUzs(rate=row.usd_uzs, snapshot_id=row.id, fetched_at=row.fetched_at, source=row.source)


async def _cache(redis: Redis, value: UsdUzs) -> None:
    payload = json.dumps(
        {
            "rate": str(value.rate),
            "snapshot_id": value.snapshot_id,
            "fetched_at": value.fetched_at.isoformat(),
            "source": value.source,
        }
    )
    with contextlib.suppress(RedisError):
        await redis.set(REDIS_KEY, payload, ex=_REDIS_TTL_SECONDS)


async def _latest(db: AsyncSession) -> FxSnapshot | None:
    return (
        await db.execute(select(FxSnapshot).order_by(FxSnapshot.fetched_at.desc()).limit(1))
    ).scalar_one_or_none()


async def record_snapshot(db: AsyncSession, *, rate: Decimal, source: str) -> FxSnapshot:
    """Insert one snapshot (flush only — the caller commits)."""
    row = FxSnapshot(id=new_id(), usd_uzs=rate, source=source, fetched_at=now())
    db.add(row)
    await db.flush()
    return row


async def current_usd_uzs(db: AsyncSession, redis: Redis, *, max_age_days: int) -> UsdUzs | None:
    """The newest rate younger than ``max_age_days``, or ``None``."""
    oldest = now() - timedelta(days=max_age_days)
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError):
        raw = await redis.get(REDIS_KEY)
        if raw is not None:
            data = json.loads(raw)
            cached = UsdUzs(
                rate=Decimal(data["rate"]),
                snapshot_id=str(data["snapshot_id"]),
                fetched_at=datetime.fromisoformat(data["fetched_at"]),
                source=str(data["source"]),
            )
            if cached.fetched_at >= oldest:
                return cached
    row = await _latest(db)
    if row is None or row.fetched_at < oldest:
        return None
    value = _of(row)
    await _cache(redis, value)
    return value


async def refresh_usd_uzs(
    db: AsyncSession,
    redis: Redis,
    *,
    fetch: Callable[[], Awaitable[Decimal]],
    source: str = "cbu",
) -> UsdUzs:
    """Fetch, record when new (or the newest row is ≥ 20 h old), **commit**, then cache.

    It commits itself so Redis never points at a snapshot a rollback erased; only the
    scheduler job and the dev seed call it.
    """
    rate = await fetch()
    latest = await _latest(db)
    if latest is not None and latest.usd_uzs == rate and now() - latest.fetched_at < _REFRESH_ROW_AFTER:
        value = _of(latest)
    else:
        value = _of(await record_snapshot(db, rate=rate, source=source))
        log.info("fx.snapshot.recorded", rate=str(rate), source=source)
    await db.commit()
    await _cache(redis, value)
    return value
```

`fx/api.py` re-exports; `fx/__init__.py` docstring; `fx/README.md`: owns `fx_snapshots`, CBU fetch, Redis copy, the 7-day rule, the 20-h row rule, no admin override yet (M3 may add one), job `fx.refresh`.

- [ ] **Step 3: Scheduler job (test first)**

```python
# apps/scheduler/tests/test_fx_refresh.py
from unittest.mock import AsyncMock

from csmarket_scheduler.jobs import fx_refresh


async def test_run_never_raises_on_cbu_error(monkeypatch) -> None:
    from csmarket.modules.fx.cbu import CbuError

    monkeypatch.setattr(fx_refresh, "_refresh_once", AsyncMock(side_effect=CbuError("down")))
    assert await fx_refresh.run() is False


async def test_run_reports_success(monkeypatch) -> None:
    monkeypatch.setattr(fx_refresh, "_refresh_once", AsyncMock(return_value=None))
    assert await fx_refresh.run() is True
```

```python
# apps/scheduler/src/csmarket_scheduler/jobs/fx_refresh.py
"""Hourly CBU USD/UZS refresh (ruling Q3). The logic is ``fx.service.refresh_usd_uzs``."""

from __future__ import annotations

from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import CbuError, fetch_usd_uzs, refresh_usd_uzs

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.fx_refresh")

JOB_ID = "fx.refresh"


async def _refresh_once() -> None:
    settings = get_settings()
    fetch = partial(fetch_usd_uzs, url=settings.fx_cbu_url, timeout=settings.fx_timeout_seconds)
    async with get_session_factory()() as db:
        await refresh_usd_uzs(db, get_redis(), fetch=fetch)


async def run() -> bool:
    """One refresh; ``False`` (logged) on any failure — the last snapshot keeps serving."""
    try:
        await _refresh_once()
    except CbuError as exc:
        log.warning("fx.refresh.failed", error=type(exc).__name__, reason=str(exc))
        return False
    except Exception:
        log.exception("fx.refresh.crashed")
        return False
    return True


def register(scheduler: AsyncIOScheduler) -> None:
    """Every ``fx_refresh_interval_minutes``; first run 20 s after start."""
    minutes = get_settings().fx_refresh_interval_minutes
    scheduler.add_job(
        run, trigger="interval", minutes=minutes, id=JOB_ID, next_run_time=first_run_after(20),
        replace_existing=True, coalesce=True, max_instances=1,
    )
```

(`CbuError` messages are fixed strings we wrote — no upstream text — so logging `reason` is safe.) Register in `main.build_scheduler`, import `csmarket.modules.fx.models` in `main.py` beside users/auth; `jobs/__init__.py` docstring lists the job; `test_main.py` expects job ids `["auth.purge_refresh_tokens", "fx.refresh"]` (sorted or in registration order — match the existing assertion style). The M1 purge job's first run is 300 s; 20 s here keeps the ≥ 15 s stagger.

- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/contract/test_cbu_rate.py tests/integration/test_fx_service.py tests/integration/test_migrations.py -q
cd ../scheduler && uv run pytest -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/fx): CBU USD/UZS rate, fx_snapshots and hourly refresh

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Waxpeer client — price snapshot, item prices, live search

**Files:**

- Modify: `apps/api/src/csmarket/modules/skins/waxpeer.py`, `apps/api/src/csmarket/modules/skins/api.py`
- Create: `apps/api/tests/fixtures/skins/{snapshot.csv,prices.json,search_v2.json}` (copied from `yupay:apps/api/tests/fixtures/skins/`)
- Test: `apps/api/tests/contract/test_waxpeer_catalogue.py`

**Interfaces:**

- Consumes: existing `WaxpeerClient`, `WaxpeerError`, `WaxpeerUnavailableError` (M1).
- Produces (added to `skins.waxpeer` and re-exported by `skins.api`):
  - `WaxpeerRateLimitedError(WaxpeerUnavailableError)` with `retry_after_seconds: float | None` (a rate limit is an outage to callers that do not care which).
  - `SnapshotRow(item_id: int, name: str, price_units: int, auto: bool)` (frozen dataclass).
  - `WaxpeerClient.iter_snapshot_rows() -> AsyncIterator[SnapshotRow]` (`GET /v1/prices/snapshot?format=csv&game=csgo`, streamed; read timeout 300 s).
  - `WaxpeerClient.prices() -> list[dict[str, Any]]` (`GET /v1/prices?game=csgo&minified=0`).
  - `WaxpeerClient.search_listings(names: list[str]) -> list[dict[str, Any]]` (`GET /v2/search-items-by-name?game=csgo&minified=0&delivery_details=1&name=…`, at most 50 names).

- [ ] **Step 1: Port the contract tests first**

`cp yupay:apps/api/tests/fixtures/skins/{snapshot.csv,prices.json,search_v2.json} apps/api/tests/fixtures/skins/` (recorded shapes, trimmed; no keys in them — grep `api=` to be sure). Port `yupay:apps/api/tests/contract/test_waxpeer_client_skins.py` through the filter as `test_waxpeer_catalogue.py`. Deltas: construct `WaxpeerClient(api_key="k", base_url="https://api.waxpeer.test/v1", timeout_seconds=5)`; the "429" tests expect `WaxpeerRateLimitedError`; the "503 / network" tests expect `WaxpeerUnavailableError` (csmarket M1 semantics: unreadable or unreachable is an outage) — where YuPay expected `WaxpeerError` for a 5xx, keep `WaxpeerError` (HTTP error status) to match M1's `_request`. Add:

```python
@respx.mock
async def test_no_key_means_no_traffic() -> None:
    route = respx.get(url__startswith="https://api.waxpeer.test/")
    client = WaxpeerClient(api_key="", base_url="https://api.waxpeer.test/v1", timeout_seconds=5)
    with pytest.raises(WaxpeerUnavailableError):
        [row async for row in client.iter_snapshot_rows()]
    with pytest.raises(WaxpeerUnavailableError):
        await client.search_listings(["AK-47 | Redline (Field-Tested)"])
    assert not route.called


@respx.mock
async def test_no_log_line_carries_the_key(capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(url__startswith="https://api.waxpeer.test/v1/prices").mock(return_value=httpx.Response(500, text="boom"))
    client = WaxpeerClient(api_key="SECRET-KEY-123", base_url="https://api.waxpeer.test/v1", timeout_seconds=5)
    with pytest.raises(WaxpeerError):
        await client.prices()
    out = capsys.readouterr()
    assert "SECRET-KEY-123" not in out.out + out.err
```

(If logs go through structlog's PrintLogger to stdout, `capsys` sees them; if the M1 tests capture differently — e.g. `test_steam_trade_hold.py` asserts via `configure_logging()` + capsys — reuse that idiom.)

Run: `uv run pytest tests/contract/test_waxpeer_catalogue.py -q` → FAIL (no such methods).

- [ ] **Step 2: Port the three reads**

From `yupay:apps/api/src/yupay/modules/fulfillment/suppliers/waxpeer_client.py` take `WaxpeerRateLimitedError` (63–68), `_SNAPSHOT_COLUMNS` (60), `SnapshotRow` (71–78), `iter_snapshot_rows` (234–296), `prices` (298–311), `search_listings` (313–355) into csmarket's `skins/waxpeer.py`. Deltas:

- Base class: `WaxpeerRateLimitedError(WaxpeerUnavailableError)`.
- Hosts: `self._host = self._base_url.removesuffix("/v1")` in `__init__` (search is `/v2`).
- Every call first refuses without a key (`WaxpeerUnavailableError("waxpeer api key is not configured")`), as `_request` does.
- Replace YuPay's `transport_error_text(exc)` with `type(exc).__name__` in the raised message and log `error=type(exc).__name__` only (M1 rule: httpx text carries the URL with `api=`).
- Logging: `log.info("waxpeer.request", method=…, path=…, status=…)` — **path without query**, as `_request` does.
- A 200 search body that is not a JSON object → `WaxpeerUnavailableError("unexpected body")` (M1 ruling P10: unreadable is an outage).
- `iter_snapshot_rows` keeps YuPay's header check (`item_id,name,price,auto` must be present; raise `WaxpeerError("snapshot columns missing")` once), skips `price <= 0` / unparseable rows and counts them (`log.info("waxpeer.snapshot.done", rows=…, bad_rows=…)`), and treats `auto == "true"`.
- Module docstring: drop "M2 adds…" — it now says what the client does: check-tradelink, price snapshot, item prices, live search; buying arrives in M4.

`skins/api.py` re-exports the new names. `skins/README.md`: extend the client paragraph with the three reads (one line each).

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/contract -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/skins): Waxpeer price snapshot, item prices and live search

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: ByMykel import, job status, daily import job

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/{bymykel,job_status}.py`, `apps/api/tests/fixtures/skins/{bymykel_skins.json,bymykel_agents.json}` (copied from YuPay), `apps/scheduler/src/csmarket_scheduler/jobs/skins_catalog_import.py`
- Modify: `apps/scheduler/src/csmarket_scheduler/main.py` (register + import skins models), `jobs/__init__.py`, `apps/scheduler/tests/test_main.py`
- Test: `apps/api/tests/unit/test_skins_bymykel.py`, `apps/api/tests/integration/test_skins_import.py`, `apps/api/tests/integration/test_skins_job_status.py`, `apps/scheduler/tests/test_skins_catalog_import.py`

**Interfaces:**

- Consumes: `SkinItem`, `naming`, `slugs`, `taxonomy` (Task 1), `core.redis`.
- Produces:
  - `skins.bymykel`: `SKINS_FILE`, `FILES`, `CatalogRow`, `ImportSummary(files, rows, changed)`, `rows_from_skins(entries)`, `rows_from_file(file_key, entries)`, `dedupe(rows)`, `async fetch_file(http, base_url, file_key)`, `async upsert_items(db, rows) -> int`, `async import_catalog(session_factory, *, base_url, http=None) -> ImportSummary`.
  - `skins.job_status`: `JOB_IMPORT = "import"`, `JOB_PRICE_SYNC = "price_sync"`, `JobStatus(finished_at: datetime, ok: bool, counters: dict[str, int], error: str | None)` (frozen dataclass), `async record_job(redis, job: str, *, ok: bool, counters: dict[str, int], error: str | None = None) -> None` (key `skins:job:{job}`, no TTL, Redis errors suppressed), `async read_job(redis, job: str) -> JobStatus | None`.
  - Scheduler job `skins.catalog_import` (interval `skins_import_interval_hours`, first run `first_run_after(120)`), skipped while `skins_sync_enabled` is false.

- [ ] **Step 1: Job status (test first)**

```python
# apps/api/tests/integration/test_skins_job_status.py
from csmarket.core.redis import get_redis
from csmarket.modules.skins.job_status import JOB_IMPORT, read_job, record_job


async def test_round_trip() -> None:
    await record_job(get_redis(), JOB_IMPORT, ok=True, counters={"files": 11, "rows": 35000, "changed": 12})
    got = await read_job(get_redis(), JOB_IMPORT)
    assert got is not None and got.ok and got.counters["rows"] == 35000 and got.error is None


async def test_unknown_job_is_none() -> None:
    assert await read_job(get_redis(), "never-ran") is None
```

```python
# apps/api/src/csmarket/modules/skins/job_status.py
"""Last outcome of the catalogue jobs, for the admin status card (ruling Q6).

Written by the scheduler after every run, read by ``GET /admin/skins/catalog/status``.
Redis only, no TTL: losing it to a flush costs a status line until the next run.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.clock import now

JOB_IMPORT = "import"
JOB_PRICE_SYNC = "price_sync"


def _key(job: str) -> str:
    return f"skins:job:{job}"


@dataclass(frozen=True)
class JobStatus:
    """One run's outcome. ``error`` is our own short label, never upstream text."""

    finished_at: datetime
    ok: bool
    counters: dict[str, int]
    error: str | None


async def record_job(
    redis: Redis, job: str, *, ok: bool, counters: dict[str, int], error: str | None = None
) -> None:
    """Store the outcome; a Redis error is swallowed (status is advisory)."""
    payload = json.dumps(
        {"finished_at": now().isoformat(), "ok": ok, "counters": counters, "error": error}
    )
    with contextlib.suppress(RedisError):
        await redis.set(_key(job), payload)


async def read_job(redis: Redis, job: str) -> JobStatus | None:
    """The last outcome, or ``None`` when unknown or unreadable."""
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError):
        raw = await redis.get(_key(job))
        if raw is None:
            return None
        data = json.loads(raw)
        return JobStatus(
            finished_at=datetime.fromisoformat(data["finished_at"]),
            ok=bool(data["ok"]),
            counters={str(k): int(v) for k, v in dict(data["counters"]).items()},
            error=None if data["error"] is None else str(data["error"]),
        )
    return None
```

- [ ] **Step 2: Port `bymykel.py` with its tests**

Copy `bymykel_skins.json`, `bymykel_agents.json` fixtures. Port `yupay-skins:bymykel.py` through the filter. Deltas: logger `csmarket.skins.bymykel`; module docstring cites "spec §2 (our catalogue is ours)" instead of YuPay spec sections; `fetch_file` must not log the URL with query (there is none — fine) and must raise on non-200 (check YuPay does `resp.raise_for_status()`; keep). `upsert_items` writes metadata columns only and **never touches `hidden`** — add `hidden` to the comment listing untouched columns.

Port `yupay:apps/api/tests/unit/test_skins_bymykel.py` and `yupay:apps/api/tests/integration/test_skins_import.py` through the filter (fixture paths `tests/fixtures/skins/…`). Add to the integration file:

```python
async def test_reimport_keeps_hidden_and_prices(db_session: AsyncSession, session_factory) -> None:
    # session_factory: async_sessionmaker bound to db_session's engine — build it from
    # db_engine the same way the ported tests do.
    await _import_fixture(session_factory)            # the ported helper
    item = (await db_session.execute(select(SkinItem).limit(1))).scalar_one()
    item.hidden = True
    item.min_auto_units = 12_345
    await db_session.commit()
    await _import_fixture(session_factory)
    await db_session.refresh(item)
    assert item.hidden is True and item.min_auto_units == 12_345
```

- [ ] **Step 3: Scheduler job (test first)**

```python
# apps/scheduler/tests/test_skins_catalog_import.py
from unittest.mock import AsyncMock

from csmarket.modules.skins.bymykel import ImportSummary
from csmarket_scheduler.jobs import skins_catalog_import as job


async def test_skipped_while_sync_disabled(monkeypatch) -> None:
    imp = AsyncMock()
    monkeypatch.setattr(job, "import_catalog", imp)
    monkeypatch.setattr(job, "_sync_enabled", lambda: False)
    await job.run()
    imp.assert_not_awaited()


async def test_records_success(monkeypatch) -> None:
    rec = AsyncMock()
    monkeypatch.setattr(job, "_sync_enabled", lambda: True)
    monkeypatch.setattr(job, "import_catalog", AsyncMock(return_value=ImportSummary(files=11, rows=10, changed=2)))
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args.kwargs == {"ok": True, "counters": {"files": 11, "rows": 10, "changed": 2}, "error": None}


async def test_records_failure_without_raising(monkeypatch) -> None:
    rec = AsyncMock()
    monkeypatch.setattr(job, "_sync_enabled", lambda: True)
    monkeypatch.setattr(job, "import_catalog", AsyncMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args.kwargs["ok"] is False and rec.await_args.kwargs["error"] == "RuntimeError"
```

Port `yupay:apps/scheduler/src/yupay_scheduler/jobs/skins_catalog_import.py` through the filter as `skins_catalog_import.py`. Deltas: the run function is `run()` (module-level, as M1's purge job); `_sync_enabled()` returns `get_settings().skins_sync_enabled`; on success `record_job(get_redis(), JOB_IMPORT, ok=True, counters={"files":…, "rows":…, "changed":…}, error=None)`; on any exception `log.exception("skins.import.failed")` and `record_job(…, ok=False, counters={}, error=type(exc).__name__)`, never re-raise; `register` uses `skins_import_interval_hours`, `first_run_after(120)`, `JOB_ID = "skins.catalog_import"`. Register in `main.py`, import `csmarket.modules.skins.models` there; update `test_main.py` job list.

- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_skins_bymykel.py tests/integration/test_skins_import.py tests/integration/test_skins_job_status.py -q
cd ../scheduler && uv run pytest -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/skins): ByMykel catalogue import with daily job and status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Price sync — 5-minute snapshot, stored prices, catalogue version

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/{cachekeys,prices}.py`, `apps/scheduler/src/csmarket_scheduler/jobs/skins_price_sync.py`
- Modify: `apps/scheduler/src/csmarket_scheduler/main.py`, `jobs/__init__.py`, `apps/scheduler/tests/test_main.py`
- Test: `apps/api/tests/unit/test_skins_prices.py`, `apps/api/tests/integration/test_skins_price_sync.py`, `apps/api/tests/integration/test_skins_price_edge_cases.py`, `apps/api/tests/integration/test_skins_reprice_lock.py`, `apps/scheduler/tests/test_skins_price_sync.py`

**Interfaces:**

- Consumes: `WaxpeerClient.iter_snapshot_rows/prices`, `SnapshotRow` (Task 4); `reprice_rows`, `lock_pricing`, `load_rules` (Task 2); naming/slugs/taxonomy (Task 1); `job_status` (Task 5).
- Produces:
  - `skins.cachekeys`: `CATALOG_VERSION_KEY = "skins:catalog:ver"`, `async catalog_version(redis) -> int` (0 on a Redis error), `async bump_catalog_version(redis) -> None` (errors suppressed). Neutral module so the read path never imports the Waxpeer client.
  - `skins.prices`: `CHEAPEST_KEPT = 10`, `MIN_SNAPSHOT_SHARE = 0.5`, `PriceAggregate`, `ApplyResult(changed: int, deactivated: int, stubs: int, refused: bool = False)`, `aggregate(rows)`, `async aggregate_stream(rows)`, `price_hash(agg)`, `async apply_prices(db, aggregates, *, meta, at) -> ApplyResult`, `async sync_prices(session_factory, client, redis) -> ApplyResult`.
  - Scheduler job `skins.price_sync` (interval `skins_snapshot_interval_minutes`, first run `first_run_after(60)`), skipped unless `skins_sync_enabled` **and** a Waxpeer key are set; records `JOB_PRICE_SYNC` status.

- [ ] **Step 1: `cachekeys.py` (unit test first)**

```python
# appended to apps/api/tests/unit/test_skins_prices.py after porting (Step 2)
async def test_catalog_version_is_zero_when_redis_is_down() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    from csmarket.modules.skins.cachekeys import bump_catalog_version, catalog_version

    class Down:
        async def get(self, *_: object) -> None:
            raise RedisConnectionError("down")

        async def incr(self, *_: object) -> None:
            raise RedisConnectionError("down")

    assert await catalog_version(Down()) == 0  # type: ignore[arg-type]
    await bump_catalog_version(Down())  # type: ignore[arg-type]  # no raise
```

```python
# apps/api/src/csmarket/modules/skins/cachekeys.py
"""The catalogue cache version (an integer every cached page key carries).

Kept apart from ``prices`` so the read path (``service``, ``routes``) never imports the
Waxpeer client. Any write that changes what a visitor sees — a price tick, hiding an
item, an alias edit — bumps it after its commit, and every cached page expires at once.
"""

from __future__ import annotations

import contextlib

from redis.asyncio import Redis
from redis.exceptions import RedisError

CATALOG_VERSION_KEY = "skins:catalog:ver"


async def catalog_version(redis: Redis) -> int:
    """The current version; 0 when Redis is unreadable (pages then just miss the cache)."""
    with contextlib.suppress(RedisError, ValueError, TypeError):
        raw = await redis.get(CATALOG_VERSION_KEY)
        return int(raw) if raw is not None else 0
    return 0


async def bump_catalog_version(redis: Redis) -> None:
    """+1; a Redis error is swallowed (the 60 s page TTL bounds staleness anyway)."""
    with contextlib.suppress(RedisError):
        await redis.incr(CATALOG_VERSION_KEY)
```

(YuPay's `service.catalog_version` and `prices.bump_catalog_version` move here; Task 7's `service.py` imports from `cachekeys`, not from `prices`.)

- [ ] **Step 2: Port `prices.py` and its tests**

`sed -f scripts/port-rename.sed yupay-skins:prices.py > apps/api/src/csmarket/modules/skins/prices.py`. Deltas:

- Imports: `SnapshotRow, WaxpeerClient` from `csmarket.modules.skins.waxpeer`; `CATALOG_VERSION_KEY`/`bump_catalog_version` from `cachekeys` (delete the local definitions; keep re-exporting `bump_catalog_version` in `__all__` only if something imports it from here — prefer importing from `cachekeys` everywhere).
- `ApplyResult` gains `refused: bool = False`; the thin-snapshot branch returns `ApplyResult(changed=0, deactivated=0, stubs=0, refused=True)`.
- Logger `csmarket.skins.prices`; comments that say "supplier" say "Waxpeer".
- `apply_prices` never writes `hidden` (state it in the docstring's list of untouched columns).

Port through the filter: `yupay:apps/api/tests/unit/test_skins_prices.py` → `tests/unit/test_skins_prices.py`; `yupay:apps/api/tests/integration/test_skins_price_sync.py` → `tests/integration/test_skins_price_sync.py`; `yupay:apps/api/tests/integration/test_skins_review_fixes.py` → `tests/integration/test_skins_price_edge_cases.py` keeping its six import/price tests (`test_names_that_fold_to_one_slug_both_import`, `test_stub_slug_collision_does_not_abort_the_tick`, `test_a_value_that_appears_later_is_written`, `test_phaseless_doppler_stub_stays_hidden`, `test_zero_steam_price_is_stored_as_unknown`, `test_a_collapsed_snapshot_is_refused` — this last one is Review Focus 3; extend it with `assert result.refused is True` and that no previously active row went inactive); move `test_discount_sort_survives_zero_steam_and_pages_negatives` to Task 7 (it hits the route). Port `yupay:apps/api/tests/integration/test_skins_reprice_lock.py` keeping `test_reprice_reads_only_the_pricing_columns`, `test_reprice_clears_a_deactivated_rows_price`, `test_the_price_tick_locks_then_reads_rules_from_postgres`; drop the two admin-route tests (rules PUT and item pin are M4) and inline whatever helper they imported from `test_skins_admin_pricing`.

Test deltas common to all ported files: settings flags are gone (no `CS2_SKINS_ENABLED`); `get_settings.cache_clear()` calls stay only where a test changes env; fixture paths `tests/fixtures/skins/…`; Waxpeer is mocked with respx on `https://api.waxpeer.test` as before.

Run: `cd apps/api && uv run pytest tests/unit/test_skins_prices.py tests/integration/test_skins_price_sync.py tests/integration/test_skins_price_edge_cases.py tests/integration/test_skins_reprice_lock.py -q` → PASS.

- [ ] **Step 3: Scheduler job (test first)**

```python
# apps/scheduler/tests/test_skins_price_sync.py
from unittest.mock import AsyncMock

from csmarket.modules.skins.prices import ApplyResult
from csmarket.modules.skins.waxpeer import WaxpeerRateLimitedError
from csmarket_scheduler.jobs import skins_price_sync as job


def _enable(monkeypatch, *, sync: bool = True, key: str = "k") -> None:
    monkeypatch.setattr(job, "_settings_ok", lambda: sync and bool(key))


async def test_skipped_without_flag_or_key(monkeypatch) -> None:
    sync = AsyncMock()
    monkeypatch.setattr(job, "sync_prices", sync)
    _enable(monkeypatch, key="")
    await job.run()
    sync.assert_not_awaited()


async def test_records_a_good_tick(monkeypatch) -> None:
    rec = AsyncMock()
    _enable(monkeypatch)
    monkeypatch.setattr(job, "sync_prices", AsyncMock(return_value=ApplyResult(changed=5, deactivated=1, stubs=0)))
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args.kwargs["ok"] is True
    assert rec.await_args.kwargs["counters"] == {"changed": 5, "deactivated": 1, "stubs": 0}


async def test_a_refused_tick_is_not_ok(monkeypatch) -> None:
    rec = AsyncMock()
    _enable(monkeypatch)
    monkeypatch.setattr(job, "sync_prices", AsyncMock(return_value=ApplyResult(0, 0, 0, refused=True)))
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args.kwargs["ok"] is False and rec.await_args.kwargs["error"] == "thin_snapshot"


async def test_waxpeer_trouble_is_recorded_not_raised(monkeypatch) -> None:
    rec = AsyncMock()
    _enable(monkeypatch)
    monkeypatch.setattr(job, "sync_prices", AsyncMock(side_effect=WaxpeerRateLimitedError("429")))
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args.kwargs == {"ok": False, "counters": {}, "error": "WaxpeerRateLimitedError"}
```

(`WaxpeerRateLimitedError`'s constructor follows Task 4 — pass whatever it takes.) Port `yupay:apps/scheduler/src/yupay_scheduler/jobs/skins_price_sync.py` through the filter. Deltas: module-level `run()`; `_settings_ok()` = `settings.skins_sync_enabled and bool(settings.waxpeer_api_key)`; client timeout `waxpeer_request_timeout_seconds`; log `error=type(exc).__name__` (never `str(exc)` — Waxpeer text may echo the request); record status as the tests say (refused → `error="thin_snapshot"`); `JOB_ID = "skins.price_sync"`, `first_run_after(60)`. Register in `main.py`; update `test_main.py`.

- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_skins_prices.py tests/integration -k "skins_price or reprice" -q
cd ../scheduler && uv run pytest -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/skins): 5-minute Waxpeer price sync with stored sell prices

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Public read API — catalogue, facets, suggest, item, SEO slugs (soʻm at the CBU rate)

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/{service,schemas,routes,seo_routes}.py`
- Modify: `apps/api/src/csmarket/api/v1/router.py` (mount `seo_router` **before** `skins_router`), `apps/api/src/csmarket/modules/skins/api.py`, `apps/api/tests/unit/test_import_order.py` (skins modules), `docs/api/openapi.json`
- Test: `apps/api/tests/unit/test_skins_cursor.py`, `apps/api/tests/integration/test_skins_catalog_routes.py`, `apps/api/tests/integration/test_skins_facets_scoped.py`, `apps/api/tests/integration/test_skins_catalog_resilience.py`

**Interfaces:**

- Consumes: models, pricing (`quote`, `to_uzs`), `settings.load_rules/enabled_categories`, `images.steam_image`, `cachekeys.catalog_version`, `fx.api.current_usd_uzs`.
- Produces:
  - `skins.service`: `Sort = Literal["price", "-price", "discount", "popular"]`, `CatalogQuery`, `Facets`, `encode_cursor`, `decode_cursor`, `async expand_aliases(db, q)`, `async list_items(db, query, *, categories)`, `async facets(db, *, categories, category=None)`, `async suggest(db, q, *, categories, limit=10)`, `async get_item(db, slug, *, categories) -> SkinItem` (404 on unknown **or hidden**), `async family(db, item, *, categories)`, `RARITY_TIER`, `WEAPON_PRIORITY`. Every public read excludes `hidden`.
  - `skins.schemas`: `SkinItemOut`, `SkinsPageOut`, `FacetOut`, `RarityFacetOut`, `SkinFacetsOut`, `SkinSuggestOut`, `SkinListingSummaryOut`, `SkinFamilyMemberOut`, `SkinDetailOut` (no `buy_sku_id`), `SkinStickerOut`, `SkinListingOut`, `SkinListingsOut`, `SkinSlugsOut`.
  - `skins.routes.router` (prefix `/skins`): `GET /skins/catalog`, `GET /skins/facets`, `GET /skins/suggest`, `GET /skins/{slug}` — query params and shapes exactly YuPay's (`category, weapon, exterior, stattrak, souvenir, rarity, team, min_uzs, max_uzs, q, sort (default `-price`), cursor, limit 1..100 default 48`). Helper `async usd_uzs_rate(db) -> Decimal | None` (used again by Task 8).
  - `skins.seo_routes.router` (prefix `/skins/seo`): `GET /skins/seo/slugs?offset&limit` → `SkinSlugsOut {items: list[str], total: int}`.

- [ ] **Step 1: Port service + cursor test**

Port `yupay-skins:service.py` and `yupay:apps/api/tests/unit/test_skins_cursor.py` through the filter. Deltas in `service.py`:

- `_base(categories)` adds `SkinItem.hidden.is_(False)`; `facets()` adds it to `live`; `family()` adds it to its where-clause; `get_item()` filters `SkinItem.hidden.is_(False)` (a hidden slug is `NotFoundError`, ruling Q4) and keeps returning inactive (sold-out) rows.
- `catalog_version` is no longer defined here — import it from `cachekeys` where `routes` needs it.
- Logger/comments renamed; no `supplier`.

- [ ] **Step 2: Schemas and routes (port the route tests first)**

Port `yupay:apps/api/tests/integration/test_skins_catalog_routes.py` and `test_skins_facets_scoped.py` through the filter, plus `test_discount_sort_survives_zero_steam_and_pages_negatives` from YuPay's `test_skins_review_fixes.py` (into `test_skins_catalog_routes.py`). Deltas: delete `test_routes_404_while_disabled` and `test_seo_slugs_404_while_disabled` (no flag, ruling Q1) and every `CS2_SKINS_ENABLED` env poke; the FX setup (`build_default_service().publish_quote_setting(ManualOverride(... manual_rate=Decimal("12700") ...))`) becomes:

```python
from csmarket.modules.fx.api import record_snapshot

async def _rate(db: AsyncSession, value: str = "12700") -> None:
    await record_snapshot(db, rate=Decimal(value), source="cbu")
    await db.commit()
```

called from the `seeded` fixture. Image-host assertions use `community.fastly.steamstatic.com`. Alias test seeds `SkinSearchAlias(alias="ак", text="ak-47")` itself (none are seeded by migrations — ruling Q13).

New file `apps/api/tests/integration/test_skins_catalog_resilience.py` (Review Focus 2):

```python
"""The catalogue renders without a rate and without Redis (Review Focus 2)."""

from decimal import Decimal

from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.ids import new_id
from csmarket.modules.skins.models import SkinItem


async def _priced(db: AsyncSession, *, slug: str, usd: str) -> None:
    db.add(
        SkinItem(
            id=new_id(), market_hash_name=f"AK-47 | {slug} (Field-Tested)", phase="", slug=slug,
            category="rifles", weapon="AK-47", exterior="FT", search_text=f"ak 47 {slug}",
            active=True, min_auto_units=int(Decimal(usd) * 1000), count_auto=3,
            sell_price_usd=Decimal(usd), source="bymykel",
        )
    )
    await db.commit()


async def test_catalog_without_fx_shows_usd_and_ignores_uzs_bounds(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _priced(db_session, slug="cheap", usd="1.00")
    await _priced(db_session, slug="dear", usd="100.00")
    r = await integration_client.get("/api/v1/skins/catalog", params={"min_uzs": "500000"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["slug"] for i in items} == {"cheap", "dear"}  # bound ignored, not guessed
    assert all(i["price_uzs"] is None and i["price_usd"] for i in items)


async def test_catalog_survives_redis_down(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    await _priced(db_session, slug="cheap", usd="1.00")

    class Down:
        def __getattr__(self, _name: str):  # every Redis call fails
            async def _fail(*_a: object, **_k: object) -> None:
                raise RedisConnectionError("down")

            return _fail

    import csmarket.modules.skins.routes as routes

    monkeypatch.setattr(routes, "get_redis", lambda: Down())
    r = await integration_client.get("/api/v1/skins/catalog")
    assert r.status_code == 200 and [i["slug"] for i in r.json()["items"]] == ["cheap"]
    assert (await integration_client.get("/api/v1/skins/cheap")).status_code == 200
```

Port `yupay-skins:schemas.py` through the filter keeping only the public DTOs listed in **Produces** (drop `buy_sku_id` from `SkinDetailOut`, `ResolveTradeIn`, `SkinsPricingOut`, `SkinQuoteOut`, `SkinItemPricingIn`, `AdminSkinItemOut`, `AdminSkinItemsOut`); add `SkinSlugsOut` (moved from YuPay's `seo_routes.py`).

Port `yupay-skins:routes.py` through the filter. Deltas:

- Remove `_ensure_enabled` and the router dependency: `router = APIRouter(prefix="/skins", tags=["skins"])`.
- Replace `_fx()` / `_uzs_rate()` with:

```python
async def usd_uzs_rate(db: AsyncSession) -> Decimal | None:
    """Soʻm per dollar for display, or ``None`` (pages then show dollars — ruling Q3)."""
    settings = get_settings()
    fx = await current_usd_uzs(db, get_redis(), max_age_days=settings.fx_max_age_days)
    return None if fx is None else fx.rate
```

and call `rate = await usd_uzs_rate(db)` wherever YuPay called `_uzs_rate(_fx())`.

- `settings.cs2_skins_image_host` → `settings.skins_image_host`.
- `get_detail`: delete `_buy_sku_id` and the `buy_sku_id=` kwarg (and the `select` import if unused).
- Move `/{slug}/listings` **out** (Task 8 adds it); keep `/catalog`, `/facets`, `/suggest`, `/{slug}`.
- `_cached()` imports `catalog_version` from `cachekeys`; keep the 60 s TTL and the sha1 digest key (with its `noqa: S324` justification).
- Default `sort` is `"-price"` (spec §2 — YuPay's route defaulted to `"price"` and relied on the web to send `-price`); the web keeps omitting the param for the default (Task 11's `skinQueryString` drops it).

Port `yupay-skins:seo_routes.py` through the filter: no `_ensure_enabled`; the slugs query adds `SkinItem.hidden.is_(False)`; `SkinSlugsOut` from `schemas`.

Mount in `api/v1/router.py`, alphabetical but with the ordering constraint written as a comment:

```python
from csmarket.modules.skins.routes import router as skins_router
from csmarket.modules.skins.seo_routes import router as skins_seo_router
...
# /skins/seo/* must precede /skins/{slug}, which would otherwise swallow it.
router.include_router(skins_seo_router)
router.include_router(skins_router)
```

`skins/api.py` keeps re-exporting the client and adds nothing route-related (routers are mounted from `routes.py`). Add `csmarket.modules.skins.routes`, `seo_routes` and `service` to `test_import_order.py`'s module list.

Regenerate `docs/api/openapi.json`.

Run: `cd apps/api && uv run pytest tests/unit/test_skins_cursor.py tests/integration/test_skins_catalog_routes.py tests/integration/test_skins_facets_scoped.py tests/integration/test_skins_catalog_resilience.py tests/unit/test_import_order.py -q` → PASS (RED first: routes missing).

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/skins): public catalogue, facets, suggest, item and sitemap slugs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Live listings — cached, budgeted, degradable Waxpeer search

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/listings.py`
- Modify: `apps/api/src/csmarket/modules/skins/routes.py` (+ `GET /skins/{slug}/listings`), `docs/api/openapi.json`
- Test: `apps/api/tests/unit/test_skins_listings.py`, `apps/api/tests/integration/test_skins_listings_route.py`

**Interfaces:**

- Consumes: `WaxpeerClient.search_listings`, `WaxpeerRateLimitedError`, `WaxpeerUnavailableError`, `WaxpeerError` (Task 4); `get_item`, `usd_uzs_rate`, schemas (Task 7); `auth.api.guard_ip`.
- Produces: `skins.listings`: `FRESH_TTL = 90`, `STALE_TTL = 3600`, `BREAKER_TTL = 120`, `SearchClient` (Protocol), `Listing`, `waxpeer_name_of(item) -> str`, `async listings_for(item, *, client, redis, budget_per_minute) -> tuple[list[Listing], bool]`; route `GET /api/v1/skins/{slug}/listings` → `SkinListingsOut {items, degraded}`, guarded by `guard_ip(request, bucket="skins-listings")`.

- [ ] **Step 1: Port tests, then code**

Port `yupay:apps/api/tests/unit/test_skins_listings.py` and `yupay:apps/api/tests/integration/test_skins_listings_route.py` through the filter (fixture `tests/fixtures/skins/search_v2.json`; FX setup → `record_snapshot` as in Task 7). Add to the integration file (Review Focus 2):

```python
async def test_listings_degrade_without_key(
    integration_client: AsyncClient, seeded_item: str, monkeypatch
) -> None:
    # seeded_item: the ported fixture's slug of an active item with cheapest_auto set
    monkeypatch.setenv("CSMARKET_WAXPEER_API_KEY", "")
    from csmarket.core import config as cfg

    cfg.get_settings.cache_clear()
    route = respx.get(url__startswith="https://api.waxpeer.test/")
    r = await integration_client.get(f"/api/v1/skins/{seeded_item}/listings")
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True and body["items"]  # snapshot's cheapest offers
    assert not route.called
```

(wrap with `@respx.mock`; restore settings with the ported files' env helper.)

Port `yupay-skins:listings.py` through the filter. Deltas: imports from `csmarket.modules.skins.waxpeer`; logger `csmarket.skins.listings`; log Waxpeer failures with `error=type(exc).__name__` only; Redis keys unchanged (`skins:listings:{slug}`, `…:stale`, `skins:wax:breaker`, `skins:wax:budget:{YYYYMMDDHHMM}`).

Add the route to `routes.py` from YuPay's `get_listings` with deltas: `rate = await usd_uzs_rate(db)`; client timeout `settings.skins_listings_timeout_seconds`; budget `settings.skins_listings_budget_per_minute if settings.waxpeer_api_key else 0`; sticker image host `settings.skins_image_host`; the comment "Spends Waxpeer quota on a cache miss — the bucket bounds distinct items per address". A hidden or unknown slug → 404 via `get_item` before any Waxpeer call.

Regenerate `docs/api/openapi.json`.

- [ ] **Step 2: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_skins_listings.py tests/integration/test_skins_listings_route.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/skins): live listings with cache, budget, breaker and snapshot fallback

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Admin audit log and admin catalogue API (status, hide, aliases)

**Files:**

- Create: `apps/api/src/csmarket/modules/admin/{models,audit}.py`, `apps/api/migrations/versions/0005_admin_audit_log.py`, `apps/api/src/csmarket/modules/skins/{admin_routes,admin_schemas}.py`
- Modify: `apps/api/migrations/env.py`, `apps/api/tests/integration/conftest.py` (`_EMPTY_IN_ORDER` + `"admin_audit_log"` before `"users"`), `apps/api/src/csmarket/api/v1/router.py`, `apps/api/src/csmarket/modules/admin/README.md`, `apps/api/tests/unit/test_import_order.py`, `docs/api/openapi.json`
- Test: `apps/api/tests/integration/test_admin_audit.py`, `apps/api/tests/integration/test_skins_admin_catalogue.py`

**Interfaces:**

- Consumes: `admin.deps.require_admin`, `core.idempotency.{normalize_idempotency_key, load_replay, save_replay, IDEMPOTENCY_HEADER}` (pattern of `users/routes.py`), `cachekeys.bump_catalog_version`, `job_status.read_job`, `fx.api.current_usd_uzs`, `SkinItem`, `SkinSearchAlias`, `naming.search_text`.
- Produces:
  - `admin.models.AdminAuditLog` — `admin_audit_log (id uuid pk, actor_user_id uuid not null fk users.id, action varchar(64) not null, target_type varchar(32) not null, target_id varchar(64) not null, payload jsonb not null default '{}', created_at timestamptz not null default now())`, index `ix_admin_audit_log_created_at (created_at)`, `ix_admin_audit_log_target (target_type, target_id)`.
  - `admin.audit.record(db, *, actor_id: str, action: str, target_type: str, target_id: str, payload: dict[str, str | int | bool | None] | None = None) -> None` (flush only).
  - Routes (prefix `/admin/skins`, `dependencies=[Depends(require_admin)]`):
    - `GET /admin/skins/catalog/status` → `CatalogStatusOut {items_total, items_active, items_hidden, prices_updated_at: datetime | None, import_job: JobOut | None, price_sync_job: JobOut | None, fx: FxOut | None, sync_enabled: bool, waxpeer_key_set: bool}`; `JobOut {finished_at, ok, counters, error}`; `FxOut {usd_uzs: str, fetched_at, source}`.
    - `GET /admin/skins/items?q=&hidden=&limit=` (q ≥ 2 chars on `search_text` ILIKE, `hidden` optional bool filter, limit 1..100 default 20, order `count_auto desc, slug`) → `AdminSkinItemsOut {items: [AdminSkinItemOut]}`; `AdminSkinItemOut {slug, name, phase, category, weapon, exterior, stattrak, souvenir, image_url, active, hidden, price_usd, count}`.
    - `PATCH /admin/skins/items/{slug}` body `{hidden: bool}` + `Idempotency-Key` → `AdminSkinItemOut`; audit `skins.item.hide` / `skins.item.unhide`, target `skin_item` / item id, payload `{"slug": slug}`; bumps the catalogue version **after** commit; unknown slug 404.
    - `GET /admin/skins/aliases` → `AliasesOut {items: [AliasOut {alias, text}]}` ordered by alias.
    - `PUT /admin/skins/aliases/{alias}` body `{text}` + `Idempotency-Key` → `AliasOut`; alias normalised `alias.strip().lower()`, 1..64 chars of letters/digits/space/hyphen (`^[\w\- ]{1,64}$` with `re.UNICODE`, no `_`), text 1..128 normalised to lower case; audit `skins.alias.put`, target `skin_alias` / alias, payload `{"alias": …, "text": …}`; bump version after commit.
    - `DELETE /admin/skins/aliases/{alias}` + `Idempotency-Key` → 204 (404 if absent); audit `skins.alias.delete`; bump version.

- [ ] **Step 1: Audit log (test first)**

```python
# apps/api/tests/integration/test_admin_audit.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.admin.audit import record
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.users.api import upsert_user_by_steam


async def test_record_writes_one_row(db_session: AsyncSession) -> None:
    admin = await upsert_user_by_steam(db_session, steam_id="76561198000000001", display_name="Owner", avatar_url=None)
    await record(db_session, actor_id=admin.id, action="skins.item.hide", target_type="skin_item", target_id="x", payload={"slug": "ak"})
    await db_session.commit()
    row = (await db_session.execute(select(AdminAuditLog))).scalar_one()
    assert (row.action, row.target_type, row.target_id, row.payload) == ("skins.item.hide", "skin_item", "x", {"slug": "ak"})
```

`admin/models.py` and `admin/audit.py` per **Produces** (`record` builds the row with `new_id()`, `created_at=now()`, `payload or {}`, `db.add`, `await db.flush()`; docstring: "Payloads name things (slugs, aliases), never people: no Steam IDs, emails or IPs."). Migration `0005_admin_audit_log.py` (`down_revision = "0004_fx_snapshots"`). `migrations/env.py` imports `csmarket.modules.admin.models`. `admin/README.md` gains the audit section.

- [ ] **Step 2: Admin catalogue routes (Review Focus 4 test first)**

```python
# apps/api/tests/integration/test_skins_admin_catalogue.py
"""Admin catalogue: status, hide/unhide, aliases (rulings Q4–Q6, Review Focus 4)."""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.ids import new_id
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.skins.models import SkinItem

KEY = "admin-catalogue-key-0001"


async def _family(db: AsyncSession) -> None:
    for ext, usd in (("FT", "10.00"), ("MW", "12.00")):
        db.add(
            SkinItem(
                id=new_id(), market_hash_name=f"AK-47 | Redline ({ext})", phase="",
                slug=f"ak-47-redline-{ext.lower()}", category="rifles", weapon="AK-47", skin="Redline",
                exterior=ext, search_text=f"ak 47 redline {ext.lower()}", active=True,
                min_auto_units=int(Decimal(usd) * 900), count_auto=5, sell_price_usd=Decimal(usd),
                cheapest_auto=[{"listing_id": 1, "price_units": int(Decimal(usd) * 900)}], source="bymykel",
            )
        )
    await record_snapshot(db, rate=Decimal("12700"), source="cbu")
    await db.commit()


async def _visible(c: AsyncClient) -> dict[str, object]:
    cat = {i["slug"] for i in (await c.get("/api/v1/skins/catalog")).json()["items"]}
    sug = {i["slug"] for i in (await c.get("/api/v1/skins/suggest", params={"q": "redline"})).json()["items"]}
    seo = set((await c.get("/api/v1/skins/seo/slugs")).json()["items"])
    rifles = dict((v, n) for v, n in ((f["value"], f["count"]) for f in (await c.get("/api/v1/skins/facets")).json()["categories"]))
    fam = {m["slug"] for m in (await c.get("/api/v1/skins/ak-47-redline-ft")).json()["family"]}
    detail = (await c.get("/api/v1/skins/ak-47-redline-mw")).status_code
    return {"cat": cat, "sug": sug, "seo": seo, "rifles": rifles.get("rifles"), "fam": fam, "detail": detail}


async def test_hide_hides_everywhere_and_unhide_restores(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers
) -> None:
    await _family(db_session)
    before = await _visible(integration_client)  # also warms the 60 s page cache
    assert "ak-47-redline-mw" in before["cat"] and before["rifles"] == 2 and before["detail"] == 200

    r = await integration_client.patch(
        "/api/v1/admin/skins/items/ak-47-redline-mw", json={"hidden": True},
        headers=await admin_headers() | {"Idempotency-Key": KEY},
    )
    assert r.status_code == 200 and r.json()["hidden"] is True
    hidden = await _visible(integration_client)
    assert "ak-47-redline-mw" not in hidden["cat"] | hidden["sug"] | hidden["seo"] | hidden["fam"]
    assert hidden["rifles"] == 1 and hidden["detail"] == 404

    r = await integration_client.patch(
        "/api/v1/admin/skins/items/ak-47-redline-mw", json={"hidden": False},
        headers=await admin_headers() | {"Idempotency-Key": KEY + "-un"},
    )
    assert r.status_code == 200
    assert await _visible(integration_client) == before

    actions = [a.action for a in (await db_session.execute(select(AdminAuditLog).order_by(AdminAuditLog.created_at))).scalars()]
    assert actions == ["skins.item.hide", "skins.item.unhide"]


async def test_a_customer_cannot_hide(integration_client: AsyncClient, db_session: AsyncSession, customer_headers) -> None:
    await _family(db_session)
    r = await integration_client.patch(
        "/api/v1/admin/skins/items/ak-47-redline-mw", json={"hidden": True},
        headers=await customer_headers() | {"Idempotency-Key": KEY},
    )
    assert r.status_code == 403


async def test_replayed_hide_writes_one_audit_row(integration_client: AsyncClient, db_session: AsyncSession, admin_headers) -> None:
    await _family(db_session)
    h = await admin_headers() | {"Idempotency-Key": KEY}
    for _ in range(2):
        assert (await integration_client.patch("/api/v1/admin/skins/items/ak-47-redline-mw", json={"hidden": True}, headers=h)).status_code == 200
    assert len((await db_session.execute(select(AdminAuditLog))).scalars().all()) == 1


async def test_alias_put_search_delete(integration_client: AsyncClient, db_session: AsyncSession, admin_headers) -> None:
    await _family(db_session)
    h = await admin_headers()
    r = await integration_client.put("/api/v1/admin/skins/aliases/РЕДЛАЙН", json={"text": "Redline"}, headers=h | {"Idempotency-Key": KEY})
    assert r.status_code == 200 and r.json() == {"alias": "редлайн", "text": "redline"}
    found = (await integration_client.get("/api/v1/skins/catalog", params={"q": "редлайн"})).json()["items"]
    assert {i["slug"] for i in found} == {"ak-47-redline-ft", "ak-47-redline-mw"}
    assert (await integration_client.get("/api/v1/admin/skins/aliases", headers=h)).json()["items"] == [{"alias": "редлайн", "text": "redline"}]
    assert (await integration_client.delete("/api/v1/admin/skins/aliases/редлайн", headers=h | {"Idempotency-Key": KEY + "-d"})).status_code == 204
    assert (await integration_client.get("/api/v1/skins/catalog", params={"q": "редлайн"})).json()["items"] == []


async def test_bad_alias_is_422(integration_client: AsyncClient, admin_headers) -> None:
    h = await admin_headers() | {"Idempotency-Key": KEY}
    assert (await integration_client.put("/api/v1/admin/skins/aliases/a_b", json={"text": "x"}, headers=h)).status_code == 422


async def test_status(integration_client: AsyncClient, db_session: AsyncSession, admin_headers) -> None:
    await _family(db_session)
    body = (await integration_client.get("/api/v1/admin/skins/catalog/status", headers=await admin_headers())).json()
    assert (body["items_total"], body["items_active"], body["items_hidden"]) == (2, 2, 0)
    assert body["fx"]["usd_uzs"] == "12700.0000" and body["sync_enabled"] is False
    assert body["import_job"] is None and body["price_sync_job"] is None
```

`admin_headers` / `customer_headers`: add two fixtures to `tests/integration/conftest.py` returning async callables that sign a user in through the M1 dev-login route (`POST /api/v1/auth/dev-login {steam_id, admin}`) and return `{"Authorization": f"Bearer {token}"}` — reuse the helper M1's `test_admin_gate.py` uses if one exists (grep `dev-login` in `tests/integration`), so there is one way to get a token in tests.

`skins/admin_schemas.py` and `skins/admin_routes.py` per **Produces**. Implementation notes:

- Follow `users/routes.py`'s idempotency pattern exactly (`normalize_idempotency_key`, `scope = f"admin.skins.item:{slug}"` / `f"admin.skins.alias:{alias}"`, `load_replay` → return the stored body; else act, `save_replay`, commit). A replay must not write a second audit row (the test pins it).
- Every mutation: change → `audit.record(...)` → `save_replay` → `await db.commit()` → `await bump_catalog_version(get_redis())`.
- Status: counts with one `select(func.count(), func.count().filter(SkinItem.active), func.count().filter(SkinItem.hidden), func.max(SkinItem.prices_updated_at))`; jobs via `read_job`; fx via `current_usd_uzs(db, redis, max_age_days=settings.fx_max_age_days)`; `waxpeer_key_set = bool(settings.waxpeer_api_key)` (never the key itself).
- Admin item search uses `ILIKE` on `search_text` with the needle folded by `naming.search_text(q, "")` and `%`/`_` escaped.
- Image URLs through `steam_image(…, host=settings.skins_image_host)`.

Mount `skins.admin_routes.router` in `api/v1/router.py`; add the two new modules to `test_import_order.py`. Regenerate `docs/api/openapi.json`.

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_admin_audit.py tests/integration/test_skins_admin_catalogue.py tests/integration/test_migrations.py tests/unit/test_import_order.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/admin): audit log and admin catalogue (status, hide, search aliases)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Dev catalogue seed (no Waxpeer needed)

**Files:**

- Create: `apps/api/src/csmarket/scripts/seed_skins_dev.py`, `apps/api/src/csmarket/scripts/dev_skins/{skins.json,agents.json,crates.json,keys.json}`
- Modify: `Makefile` (`seed-skins` target + `make help` line), `AGENTS.md` §13 (one table row), `docs/onboarding/local-setup.md` ("A catalogue to browse")
- Test: `apps/api/tests/integration/test_seed_skins_dev.py`

**Interfaces:**

- Consumes: `bymykel.rows_from_skins/rows_from_file/dedupe/upsert_items` (Task 5), `prices.aggregate/apply_prices` (Task 6), `SnapshotRow` (Task 4), `repricing.reprice_rows`, `settings.load_rules` (Task 2), `fx.api.refresh_usd_uzs`/`current_usd_uzs` (Task 3), `cachekeys.bump_catalog_version`.
- Produces: `async seed(session_factory, redis) -> int` (items made active); CLI `python -m csmarket.scripts.seed_skins_dev` (exit 2 with "refusing to seed in production" when `settings.is_prod`); `make seed-skins` = `docker compose exec api python -m csmarket.scripts.seed_skins_dev`.

- [ ] **Step 1: Build the fixture (one-off, committed output)**

Download ByMykel's files once (network; not committed) and keep a curated subset, trimmed to the keys `bymykel.rows_from_skins` / `rows_from_file` read (open `bymykel.py` and keep exactly those keys — `name`, `market_hash_name`, `weapon`, `pattern`, `category`, `rarity`, `wear`, `stattrak`, `souvenir`, `phase`, `image`, `min_float`, `max_float`, `paint_index`, `team` …; drop `description` and other long text):

```bash
BASE=https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en
mkdir -p /tmp/bymykel && for f in skins_not_grouped agents crates keys; do curl -sSfo /tmp/bymykel/$f.json $BASE/$f.json; done
```

Selection (≈ 60 entries, so every page type has data):

- `skins.json` from `skins_not_grouped`: AK-47 | Redline (all wears, + one StatTrak™ Field-Tested), AWP | Asiimov (Field-Tested, Well-Worn, Battle-Scarred), M4A4 | Howl (Field-Tested), Desert Eagle | Blaze (Factory New), Glock-18 | Water Elemental (Factory New, Minimal Wear), USP-S | Kill Confirmed (Minimal Wear), P90 | Asiimov (Field-Tested), MP9 | Starlight Protector (Field-Tested), Nova | Hyper Beast (Field-Tested), Negev | Mjölnir (Field-Tested), ★ Karambit | Doppler (Factory New, Phase 1 and Phase 2), ★ Butterfly Knife | Fade (Factory New), ★ Sport Gloves | Vice (Field-Tested), ★ Specialist Gloves | Crimson Kimono (Field-Tested), one Souvenir item (e.g. a Souvenir AWP from a Major collection).
- `agents.json`: 2 CT and 2 T agents.
- `crates.json`: 4 cases (e.g. Kilowatt, Revolution, Recoil, Dreams & Nightmares). `keys.json`: 2 keys.

Write the curated lists as pretty-printed JSON. Steam image URLs stay as ByMykel has them (public CDN). Check: `python -c "import json,sys; [json.load(open(p)) for p in sys.argv[1:]]" apps/api/src/csmarket/scripts/dev_skins/*.json` and that the four files total < 150 KB.

- [ ] **Step 2: Seed (integration test first)**

```python
# apps/api/tests/integration/test_seed_skins_dev.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.skins.models import SkinItem
from csmarket.scripts.seed_skins_dev import seed


async def test_seed_makes_a_browsable_priced_catalogue(db_engine) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    made = await seed(factory, get_redis())
    assert made >= 40
    async with factory() as db:
        active = await db.scalar(select(func.count()).select_from(SkinItem).where(SkinItem.active))
        unpriced = await db.scalar(
            select(func.count()).select_from(SkinItem).where(SkinItem.active, SkinItem.sell_price_usd.is_(None))
        )
        cats = set((await db.execute(select(SkinItem.category).where(SkinItem.active).distinct())).scalars())
        assert active == made and unpriced == 0
        assert {"rifles", "knives", "gloves", "agents", "cases"} <= cats
        assert await current_usd_uzs(db, get_redis(), max_age_days=7) is not None


async def test_seed_is_repeatable(db_engine) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    first = await seed(factory, get_redis())
    async with factory() as db:
        prices = dict((await db.execute(select(SkinItem.slug, SkinItem.sell_price_usd))).all())
    assert await seed(factory, get_redis()) == first
    async with factory() as db:
        assert dict((await db.execute(select(SkinItem.slug, SkinItem.sell_price_usd))).all()) == prices
```

`seed_skins_dev.py`:

```python
"""Fill a dev database with a small, priced catalogue — no Waxpeer key needed (ruling Q7).

The Waxpeer key works only from the production IP, so local work and e2e browse a
curated ByMykel subset with deterministic fake listings, priced through the real
``apply_prices`` + ``reprice_rows`` path. Refuses to run in production.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from decimal import Decimal
from importlib import resources

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import current_usd_uzs, refresh_usd_uzs
from csmarket.modules.skins.bymykel import SKINS_FILE, dedupe, rows_from_file, rows_from_skins, upsert_items
from csmarket.modules.skins.cachekeys import bump_catalog_version
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.prices import aggregate, apply_prices
from csmarket.modules.skins.repricing import lock_pricing, reprice_rows
from csmarket.modules.skins.settings import load_rules
from csmarket.modules.skins.waxpeer import SnapshotRow

_FILES = {"skins.json": SKINS_FILE, "agents.json": "agents", "crates.json": "crates", "keys.json": "keys"}
_DEV_RATE = Decimal("12700")
_DEAR = {"knives", "gloves"}


def _load(name: str) -> list[dict[str, object]]:
    raw = resources.files("csmarket.scripts.dev_skins").joinpath(name).read_text("utf-8")
    data = json.loads(raw)
    assert isinstance(data, list)
    return data


def _units(name: str, phase: str, category: str) -> int:
    """A stable fake price: $0.50–$200, ×20 for knives and gloves."""
    digest = int(hashlib.sha256(f"{name}|{phase}".encode()).hexdigest(), 16)
    units = 500 + digest % 200_000
    return units * 20 if category in _DEAR else units


def _rows(items: list[SkinItem]) -> list[SnapshotRow]:
    rows: list[SnapshotRow] = []
    for n, item in enumerate(items):
        base = _units(item.market_hash_name, item.phase, item.category)
        for k, factor in enumerate((Decimal("1"), Decimal("1.05"), Decimal("1.10"))):
            name = f"{item.market_hash_name} ({item.phase})" if item.phase else item.market_hash_name
            # How Waxpeer spells a phased name must match what ``prices`` folds back
            # (``naming.canonical_name``); check it against the snapshot fixture.
            rows.append(SnapshotRow(item_id=n * 10 + k + 1, name=name, price_units=int(base * factor), auto=True))
    return rows


async def seed(session_factory: async_sessionmaker[AsyncSession], redis: Redis) -> int:
    """Import the curated subset, price it, ensure an fx rate. Returns active items."""
    async with session_factory() as db:
        for fname, file_key in _FILES.items():
            entries = _load(fname)
            parsed = rows_from_skins(entries) if file_key == SKINS_FILE else rows_from_file(file_key, entries)
            await upsert_items(db, dedupe(parsed))
        await db.commit()
    async with session_factory() as db:
        items = list((await db.execute(select(SkinItem))).scalars())
        await lock_pricing(db)
        await apply_prices(db, aggregate(_rows(items)), meta=[], at=now())
        await reprice_rows(db, await load_rules(db, fresh=True))
        await db.commit()
        if await current_usd_uzs(db, redis, max_age_days=get_settings().fx_max_age_days) is None:

            async def _dev_rate() -> Decimal:
                return _DEV_RATE

            await refresh_usd_uzs(db, redis, fetch=_dev_rate, source="dev")
        active = len(list((await db.execute(select(SkinItem.id).where(SkinItem.active))).scalars()))
    await bump_catalog_version(redis)
    return active


def main() -> int:
    """CLI entry point."""
    if get_settings().is_prod:
        print("refusing to seed in production", file=sys.stderr)
        return 2
    made = asyncio.run(seed(get_session_factory(), get_redis()))
    print(f"seeded {made} active items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Adjust to the real signatures you ported (e.g. `apply_prices(meta=…)` expects Waxpeer `/v1/prices` items — an empty list is the "no metadata" case; `aggregate` may want an iterable). If `_rows` naming of Doppler phases does not round-trip, fix the spelling, not the assertion. Add `dev_skins/__init__.py` only if `importlib.resources` needs a package (it does: `csmarket.scripts.dev_skins` must be a package — add an empty `__init__.py` with a one-line docstring) and make sure the JSON files ship in the wheel/image (check `apps/api/pyproject.toml` build includes package data; add `[tool.hatch.build] include` or equivalent if the build backend skips non-`.py` files — verify with `uv build` or by listing the installed package in the dev container).

`Makefile`:

```make
seed-skins: ## Dev only: fill the catalogue with ~60 priced items (no Waxpeer key needed)
	docker compose exec api python -m csmarket.scripts.seed_skins_dev
```

AGENTS §13 row: `make seed-skins` — "Dev only: a priced ~60-item catalogue (refuses in prod)". `docs/onboarding/local-setup.md`: a short "A catalogue to browse" section (`make dev-detached && make migrate && make seed-skins`, then open `http://localhost:3100/`).

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_seed_skins_dev.py -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh && npx prettier --check .
git add -A && git commit -m "feat(api/skins): dev catalogue seed without Waxpeer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: `@csmarket/utils` skins model — query, URL state, view helpers, JSON-LD

**Files:**

- Create: `packages/utils/src/skins/{query,view,float,json-ld,money}.ts` and their `*.test.ts`, `packages/utils/src/skins/index.ts`
- Modify: `packages/utils/src/index.ts` (re-export), `packages/utils/package.json` (add `"exports": {".": "./src/index.ts", "./skins": "./src/skins/index.ts"}` if the package has no `exports` map — keep `main`/`types`)
- Test: the five `*.test.ts` above

**Interfaces:**

- Produces (`@csmarket/utils` → `skins/*`):
  - `query.ts` (from `yupay:packages/utils/src/skins.ts`): types `SkinSort`, `Exterior`, `SkinItem`, `SkinsPage`, `Facet`, `RarityFacet`, `SkinFacets`, `SkinFamilyMember`, `SkinDetail` (**no `buy_sku_id`**), `SkinListing`, `SkinListings`, `SkinQuery`; constants `SKIN_CATEGORIES`, `SKIN_TEAMS`, `EXTERIORS`, `DEFAULT_SORT = "-price"`; `parseSkinQuery(raw)`, `skinQueryString(query, patch?)`, `filterSections(category, facets, rarity)`, and **new** `isFilteredQuery(query: SkinQuery): boolean` (ruling Q9: `skinQueryString(query) !== ""`).
  - `view.ts` (from `skin-view.ts`): `offerHeadline`, `wearChoices`, `CATEGORY_ICONS`, `isVanilla`, `activeFilterCount`, `hasWear`, `wearColor`, `steamDiscount`, `rarityGlow` (**drop `repriceOffer`** — checkout, M4).
  - `float.ts` (from `skin-float.ts`): `wearBand`, `floatPosition`, `steamImageSize`, `WearBand`.
  - `json-ld.ts`: `serializeJsonLd(data: unknown): string`.
  - `money.ts`: `uzsWord(locale: string): string` (ru «сум», uz «soʻm», else «UZS») and `formatUzs(locale: string, amount: string | number): string` (`Intl.NumberFormat` with the locale's grouping + `uzsWord`; whole soʻm).

- [ ] **Step 1: Port tests first**

```bash
Y=/Users/macbook_uz/Projects/yupay/packages/utils/src
mkdir -p packages/utils/src/skins
cp $Y/skins.test.ts packages/utils/src/skins/query.test.ts
cp $Y/skin-view.test.ts packages/utils/src/skins/view.test.ts
cp $Y/skin-float.test.ts packages/utils/src/skins/float.test.ts
cp $Y/json-ld.test.ts packages/utils/src/skins/json-ld.test.ts
```

Deltas in tests: imports from `./query`, `./view`, `./float`, `./json-ld`; delete `repriceOffer` tests and any `buy_sku_id` in fixtures. Add:

```ts
// packages/utils/src/skins/query.test.ts (appended)
describe("isFilteredQuery", () => {
  it("is false for the clean catalogue and for tracking params", () => {
    expect(isFilteredQuery(parseSkinQuery({}))).toBe(false);
    expect(isFilteredQuery(parseSkinQuery({ utm_source: "tg", fbclid: "x", gclid: "y" }))).toBe(
      false,
    );
    expect(isFilteredQuery(parseSkinQuery({ sort: "-price" }))).toBe(false); // the default
  });
  it("is true for any recognised filter, sort or page", () => {
    for (const raw of [
      { category: "knives" },
      { weapon: "AK-47" },
      { exterior: "FN" },
      { rarity: "Covert" },
      { team: "ct" },
      { stattrak: "1" },
      { q: "redline" },
      { min: "1000" },
      { max: "9000" },
      { sort: "price" },
      { cursor: "abc_DEF-1" },
    ]) {
      expect(isFilteredQuery(parseSkinQuery(raw))).toBe(true);
    }
  });
});
```

```ts
// packages/utils/src/skins/money.test.ts
import { describe, expect, it } from "vitest";

import { formatUzs, uzsWord } from "./money";

describe("money", () => {
  it("names the currency per locale", () => {
    expect(uzsWord("ru")).toBe("сум");
    expect(uzsWord("uz")).toBe("soʻm");
    expect(uzsWord("en")).toBe("UZS");
  });
  it("groups whole soʻm", () => {
    expect(formatUzs("ru", "1234500")).toMatch(/^1\s234\s500 сум$/u);
    expect(formatUzs("en", 1234500)).toBe("1,234,500 UZS");
  });
});
```

(`Intl` in Node uses a narrow no-break space for `ru` grouping — the regex's `\s` with the `u` flag matches it.)

Run: `pnpm --filter @csmarket/utils test` → FAIL (modules missing).

- [ ] **Step 2: Port the sources**

Copy `skins.ts` → `query.ts`, `skin-view.ts` → `view.ts`, `skin-float.ts` → `float.ts`, `json-ld.ts` → `json-ld.ts`; write `money.ts` (`uzsWord` from `yupay:packages/utils/src/money.ts`, plus `formatUzs`). Deltas:

- Drop `buy_sku_id` from `SkinDetail`; drop `repriceOffer` and anything only it used.
- `SkinItem` matches Task 7's `SkinItemOut` exactly (field names and string money). Compare against `docs/api/openapi.json` (`SkinItemOut`, `SkinDetailOut`, `SkinFacetsOut`, `SkinListingOut`, `SkinsPageOut`) and fix any drift in the TS types.
- `CATEGORY_ICONS` file paths stay `/skins/categories/<file>.png` (Task 12 copies the PNGs).
- `DEFAULT_SORT = "-price"` (unchanged).
- Add `isFilteredQuery` beside `skinQueryString`.
- Comments mentioning YuPay, the mini app or `skinsavdo` keep only the fact ("default sort -price, as the market does").
- TS strict (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`): fix what breaks without changing behaviour.

`skins/index.ts` re-exports all five modules; `src/index.ts` adds `export * from "./skins";`.

- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/utils test && pnpm --filter @csmarket/utils lint && pnpm --filter @csmarket/utils typecheck
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(packages/utils): skins query model, URL state, view and money helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Web data layer, SEO helpers, `web.skins` copy, category icons

**Files:**

- Create: `apps/web/src/lib/{server-api,skins,paths,seo,skin-landing}.ts` (+ `skins.test.ts`, `seo.test.ts`, `skin-landing.test.ts`), `apps/web/public/skins/categories/*.png` (10 files), `scripts/i18n/port-skins-copy.py` (one-off, committed for the record)
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json` (+ `skins`), `apps/web/src/app/[locale]/layout.tsx` (title template)
- Test: `apps/web/src/lib/skins.test.ts`, `apps/web/src/lib/seo.test.ts`, `apps/web/src/lib/skin-landing.test.ts`, `packages/i18n` parity test (existing)

**Interfaces:**

- Consumes: `@csmarket/utils` skins types and helpers (Task 11); `session` from `@/lib/api` (M1) for browser calls; API routes (Tasks 7–8).
- Produces:
  - `lib/server-api.ts`: `class ApiError extends Error { status: number; path: string }`, `apiGet<T>(path, opts?: { revalidate?: number; tags?: string[] }) -> Promise<T>` (server-only fetch to `${API_INTERNAL_URL ?? NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8100"}/api/v1${path}`, `next: { revalidate: opts.revalidate ?? 60, tags: opts.tags ?? ["skins"] }`, throws `ApiError` on non-2xx), `apiGetOrNull<T>(path, opts?)` (null **only** on 404).
  - `lib/skins.ts`: `getSkinsPage(query) -> Promise<SkinsPage>` (throws on failure — ruling Q10), `getSkinFacets(category?) -> Promise<SkinFacets | null>` (null only on 404), `getSkinDetail(slug) -> Promise<SkinDetail | null>` (null only on 404), `fetchSkinSlugs(offset, limit) -> Promise<{ items: string[]; total: number }>` (revalidate 3600), browser: `fetchSkinsPage(query, signal?)`, `fetchSuggest(q, signal?)`, `fetchSkinListings(slug, signal?)` via `session.apiGet(path, { anonymous: true, signal })`; `displayPrice(locale, uzs, usd) -> string | null` (soʻm via `formatUzs`; `$usd` when `uzs` is null; null when both are).
  - `lib/paths.ts`: `HOME = "/"`, `itemPath(slug)`, `categoryPath(category)`, `weaponPath(weaponSlug)` — locale-less paths for next-intl `Link`.
  - `lib/seo.ts`: `localeUrl(locale, path) -> string` (ru without prefix, `localePrefix: "as-needed"`), `alternates(locale, path) -> { canonical: string; languages: Record<string, string> }` (ru/uz/en + `x-default` → ru), `ROBOTS = { index: true, follow: true }`, `NOINDEX_FOLLOW = { index: false, follow: true }`, `ogLocale(locale)`, `GEO_META` (Tashkent geo tags, as YuPay).
  - `lib/skin-landing.ts`: `isSkinCategory`, `weaponSlug`, `findWeapon(facets, slug)`, `landingPaths(facets) -> string[]`, `countUnit(category)`.
  - i18n: `web.skins.*` (the browse-only subset below) in ru/uz/en.

- [ ] **Step 1: Copy (`web.skins`) — port, rebrand, normalise**

Browse-only keys (everything else in YuPay's `web.skins` is checkout, trade link or dead): `meta.{title,description,itemTitle,itemTitleNoPrice,itemDescription,itemDescriptionNoPrice}`, `title`, `searchPlaceholder`, `filters`, `price`, `from`, `to`, `reset`, `wear`, `rarity`, `stattrak`, `sortLabel`, `sort.*`, `all`, `category.*`, `exterior.*`, `soldOut`, `loadMore`, `loading`, `empty`, `fromPrice`, `steamPrice`, `offers`, `inspect`, `seed`, `float`, `stickers`, `market`, `otherWears`, `noOffers`, `vanilla`, `resetFilters`, `done`, `inStock`, `pieces`, `close`, `belowSteam`, `faq.{title,priceQ,priceA,steamQ,steamA,floatQ,floatA}`, `landing.*`, `team.*`.

```python
# scripts/i18n/port-skins-copy.py — one-off; kept so the provenance is visible.
"""Copy YuPay's browse-only web.skins strings into csmarket's catalogs (M2 Task 12)."""
import json
import re
import sys
from pathlib import Path

YUPAY = Path("/Users/macbook_uz/Projects/yupay/packages/i18n/locales")
HERE = Path("packages/i18n/locales")
TOP = ["title", "searchPlaceholder", "filters", "price", "from", "to", "reset", "wear", "rarity",
       "stattrak", "sortLabel", "sort", "all", "category", "exterior", "soldOut", "loadMore",
       "loading", "empty", "fromPrice", "steamPrice", "offers", "inspect", "seed", "float",
       "stickers", "market", "otherWears", "noOffers", "vanilla", "resetFilters", "done",
       "inStock", "pieces", "close", "belowSteam", "landing", "team"]
FAQ = ["title", "priceQ", "priceA", "steamQ", "steamA", "floatQ", "floatA"]
META = ["title", "description", "itemTitle", "itemTitleNoPrice", "itemDescription", "itemDescriptionNoPrice"]


def fix_uz(text: str) -> str:
    # oʻ/gʻ take U+02BB; any other letter-apostrophe-letter is the tutuq belgisi U+02BC.
    text = re.sub(r"([oOgG])['’ʼ]", "\\1ʻ", text)
    return re.sub(r"(?<=\w)['’](?=\w)", "ʼ", text)


def walk(value, fn):
    if isinstance(value, dict):
        return {k: walk(v, fn) for k, v in value.items()}
    return fn(value) if isinstance(value, str) else value


for loc in ("ru", "uz", "en"):
    src = json.loads((YUPAY / loc / "web.json").read_text("utf-8"))["skins"]
    out = {"meta": {k: src["meta"][k] for k in META}, **{k: src[k] for k in TOP},
           "faq": {k: src["faq"][k] for k in FAQ}}
    out = walk(out, lambda s: s.replace("YuPay", "csmarket").replace("yupay", "csmarket"))
    if loc == "uz":
        out = walk(out, fix_uz)
    dst_path = HERE / loc / "web.json"
    dst = json.loads(dst_path.read_text("utf-8"))
    dst["skins"] = out
    dst_path.write_text(json.dumps(dst, ensure_ascii=False, indent=2) + "\n", "utf-8")
    assert "yupay" not in json.dumps(out).lower(), loc
print("ok", file=sys.stderr)
```

Run it from the repo root, then `npx prettier --write packages/i18n/locales`. Read the result in all three locales and fix by hand anything the rules break: copy must say «вы», carry no service meta, keep «КС2 (CS2)» in RU titles, «CS2 skins» in the UZ hub title, «CS2 skins» as the EN H1. Remove `web.home` (the hello page goes in Task 13) **in Task 13**, not here. `pnpm --filter @csmarket/i18n test` (parity) → PASS.

- [ ] **Step 2: Category icons**

```bash
mkdir -p apps/web/public/skins/categories
cp /Users/macbook_uz/Projects/yupay/apps/web/public/skins/categories/*.png apps/web/public/skins/categories/
ls apps/web/public/skins/categories | wc -l   # 10
```

(Steam CDN sends no CORS header, so a CSS mask needs same-origin files — that is why they are self-hosted.)

- [ ] **Step 3: Data and SEO helpers (tests first)**

```ts
// apps/web/src/lib/skins.test.ts — the outage-vs-404 contract (ruling Q10)
import { afterEach, describe, expect, it, vi } from "vitest";

import { getSkinDetail, getSkinFacets, getSkinsPage } from "./skins";

const res = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("skins data", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("a 404 is null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(404)));
    await expect(getSkinDetail("nope")).resolves.toBeNull();
    await expect(getSkinFacets("nope")).resolves.toBeNull();
  });

  it("an outage throws — never a 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(503)));
    await expect(getSkinDetail("ak")).rejects.toThrow();
    await expect(getSkinFacets()).rejects.toThrow();
    await expect(getSkinsPage({ sort: "-price" })).rejects.toThrow();
  });

  it("asks the API with the query's params", async () => {
    const f = vi.fn().mockResolvedValue(res(200, { items: [], next_cursor: null }));
    vi.stubGlobal("fetch", f);
    await getSkinsPage({ sort: "price", category: "knives", min: "1000" });
    const url = String(f.mock.calls[0]?.[0]);
    expect(url).toContain("/api/v1/skins/catalog?");
    expect(url).toContain("category=knives");
    expect(url).toContain("sort=price");
    expect(url).toContain("min_uzs=1000");
  });
});
```

(Use the real `SkinQuery` shape from Task 11; adjust the object literal to it.)

```ts
// apps/web/src/lib/seo.test.ts
import { describe, expect, it } from "vitest";

import { alternates, localeUrl } from "./seo";

describe("seo", () => {
  it("ru has no prefix, others do", () => {
    expect(localeUrl("ru", "/item/ak")).toBe("https://csmarket.uz/item/ak");
    expect(localeUrl("uz", "/item/ak")).toBe("https://csmarket.uz/uz/item/ak");
    expect(localeUrl("en", "/")).toBe("https://csmarket.uz/en");
    expect(localeUrl("ru", "/")).toBe("https://csmarket.uz/");
  });
  it("alternates carry every locale and x-default → ru", () => {
    const a = alternates("uz", "/category/knives");
    expect(a.canonical).toBe("https://csmarket.uz/uz/category/knives");
    expect(a.languages).toEqual({
      ru: "https://csmarket.uz/category/knives",
      uz: "https://csmarket.uz/uz/category/knives",
      en: "https://csmarket.uz/en/category/knives",
      "x-default": "https://csmarket.uz/category/knives",
    });
  });
});
```

Port `yupay:apps/web/src/lib/skin-landing.ts` + `skin-landing.test.ts` with `categoryPath`/`weaponPath` moved to `lib/paths.ts` (`/category/<c>`, `/weapon/<w>`) and the test's expected paths updated. Write `server-api.ts`, `skins.ts`, `paths.ts`, `seo.ts` per **Produces** (port `yupay:apps/web/src/lib/seo.ts`'s `localeUrl`/`alternates`/`ogLocale`/`GEO_META`, `SITE` from `@/lib/site`; drop its markdown alternate and anything not listed). `skins.ts` sends no `Accept-Language` and has no locale parameter (the API is locale-free; one cache entry per URL instead of three).

`[locale]/layout.tsx`: `title: { default: t("title"), template: "%s — csmarket" }` in `generateMetadata` (keep the existing `t` source).

- [ ] **Step 4: Gate, commit**

```bash
pnpm --filter @csmarket/i18n test && pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/catalogue): data layer, SEO helpers, skins copy and category icons

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Home `/` = the catalogue (filters, search, sort, infinite scroll)

**Files:**

- Create: `apps/web/src/components/skins/{SkinCard,SkinCategoryBar,SkinCategoryIcon,ScrollActiveIntoView,SkinFilters,SkinFilterDrawer,SkinPriceFilter,SkinSort,SkinSearch,SkinGridMore,SkinLandingLinks}.tsx` (+ ported tests), `apps/web/src/app/[locale]/metadata.test.ts`
- Modify: `apps/web/src/app/[locale]/page.tsx` (hello page → catalogue), `packages/i18n/locales/{ru,uz,en}/web.json` (remove `web.home`), `e2e/tests/home.spec.ts` (new H1s)
- Test: ported component tests (`SkinCard`, `SkinCategoryBar`, `SkinFilterDrawer`, `SkinFilters`, `SkinGridMore`, `SkinPriceFilter`, `SkinSearch`), `metadata.test.ts`

**Interfaces:**

- Consumes: Task 11 helpers, Task 12 data/SEO/paths/copy.
- Produces: `generateMetadata` for `/` (exported for the test) and the catalogue page; components with YuPay's props (see each file) minus anything named in the deltas.

**Design tokens (YuPay → csmarket), apply in every ported component:**

| YuPay class                                       | csmarket class                                 |
| ------------------------------------------------- | ---------------------------------------------- |
| `bg-card`                                         | `bg-surface`                                   |
| `bg-muted`                                        | `bg-surface-2`                                 |
| `border-border-2`                                 | `border-border-strong`                         |
| `text-tx`                                         | `text-fg`                                      |
| `text-tx-dim`                                     | `text-fg-dim`                                  |
| `text-tx-mute`                                    | `text-fg-muted`                                |
| `bg-primary` / `text-primary` / `text-primary-fg` | `bg-accent` / `text-accent` / `text-accent-fg` |
| `rounded-btn` / `rounded-card`                    | `rounded-md` / `rounded-lg`                    |
| `font-display`                                    | `font-sans font-bold`                          |
| `pt-[104px]` (YuPay's fixed header)               | remove — csmarket's header is in flow          |

- [ ] **Step 1: Indexability (Review Focus 5, test first)**

```ts
// apps/web/src/app/[locale]/metadata.test.ts
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
  setRequestLocale: () => undefined,
}));

import { generateMetadata } from "./page";

const meta = (searchParams: Record<string, string>) =>
  generateMetadata({
    params: Promise.resolve({ locale: "ru" }),
    searchParams: Promise.resolve(searchParams),
  });

describe("home indexability (ruling Q9)", () => {
  it("clean and tracked visits are indexable with canonical /", async () => {
    for (const sp of [{}, { utm_source: "telegram" }, { fbclid: "abc" }, { gclid: "x" }]) {
      const m = await meta(sp);
      expect(m.robots).toEqual({ index: true, follow: true });
      expect(m.alternates?.canonical).toBe("https://csmarket.uz/");
    }
  });
  it("a filtered view is noindex,follow with the same canonical", async () => {
    const m = await meta({ category: "knives" });
    expect(m.robots).toEqual({ index: false, follow: true });
    expect(m.alternates?.canonical).toBe("https://csmarket.uz/");
  });
});
```

Run → FAIL (the hello page has no such metadata).

- [ ] **Step 2: Port the components (tests first)**

For each component in **Files**, copy `yupay:apps/web/src/components/skins/<Name>.tsx` and its `<Name>.test.tsx` when it exists. Deltas for all of them:

- Imports: `@yupay/utils` → `@csmarket/utils`; `@/lib/skins` / `@/lib/seo` / `@/lib/paths` from Task 12; `pathFor(locale, "/skins/<slug>")` → `itemPath(slug)` with next-intl `Link` from `@/i18n/navigation` (which adds the locale); every hard-coded `PATH = "/skins"` → `HOME` (`/`).
- i18n namespace stays `web.skins`; tests wrap in `NextIntlClientProvider` with `messages={{ web: ru, common }}` importing `@csmarket/i18n/locales/ru/web.json` (as M1's tests do).
- Tokens per the table above.
- `SkinSearch`: browser call `fetchSuggest(q, signal)` from `@/lib/skins` (anonymous `session.apiGet`); keep debounce 250 ms, min 2 chars, `AbortController`; the test mocks `@/lib/skins` instead of `@/lib/client`.
- `SkinGridMore`: `fetchSkinsPage(query, signal)` (no locale arg).
- `SkinPriceFilter`: keep the no-JS GET form; **add `team`** to its hidden inputs (YuPay missed it).
- `SkinFilterDrawer`: `z-[60]` → `z-50` (csmarket header has no z-index above content).
- Comments: no YuPay/mini-app/`skinsavdo` mentions.

- [ ] **Step 3: The page**

Replace `app/[locale]/page.tsx` with a port of `yupay:apps/web/src/app/[locale]/skins/page.tsx`. Deltas:

- `generateMetadata({ params, searchParams })` (exported): title/description from `web.skins.meta`; `alternates: alternates(locale, HOME)`; `robots: isFilteredQuery(parseSkinQuery(raw)) ? NOINDEX_FOLLOW : ROBOTS` (ruling Q9); `openGraph: { type: "website", siteName: "csmarket", locale: ogLocale(locale) }`; `other: GEO_META`.
- Data: `Promise.all([getSkinsPage(query), getSkinFacets(query.category)])`. If facets is `null` (an API 404 — only a bad `category` causes it) render the catalogue without the category bar instead of `notFound()` — the home page never 404s (ruling Q10). An outage throws into `[locale]/error.tsx`.
- `SkinLandingLinks` only when `!isFilteredQuery(query)`.
- `setRequestLocale` with the existing eslint-disable comment.
- Main landmark `id="main-content"`; no `loading.tsx` anywhere under `app/` (Task 14 adds a guard test).

Remove `web.home` from the three locale files (parity). Update `e2e/tests/home.spec.ts`'s three cases to the new H1s (`web.skins.title` in ru/uz/en) and rename the test to "catalogue renders in …"; leave the robots case for Task 15.

- [ ] **Step 4: Gate, commit**

```bash
pnpm --filter @csmarket/web test && pnpm --filter @csmarket/i18n test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/catalogue): the home page is the catalogue

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(The build must not need a running API: `/` is dynamic — it reads `searchParams`. If `next build` tries to prerender it and fails on fetch, add `export const dynamic = "force-dynamic"` with a comment.)

---

### Task 14: Item page `/item/[slug]` — wears, live offers, FAQ, JSON-LD, real 404

**Files:**

- Create: `apps/web/src/app/[locale]/item/[slug]/page.tsx`, `apps/web/src/components/JsonLd.tsx`, `apps/web/src/components/skins/{SkinHero,SkinWearPicker,SkinFloatBar,SkinPriceBlock,SkinOffers,SkinListings,SkinFaq}.tsx` (+ ported tests), `apps/web/src/lib/skin-seo.ts` (+ test), `apps/web/src/app/no-loading-boundaries.test.ts`
- Test: ported `SkinHero`, `SkinListings`, `SkinPriceBlock`, `SkinWearPicker` tests, `skin-seo.test.ts`, `no-loading-boundaries.test.ts`, `apps/web/src/app/[locale]/item/[slug]/page.test.ts`

**Interfaces:**

- Consumes: Tasks 11–13.
- Produces: the item page; `lib/skin-seo.ts`: `wearFloatRange(item)`, `skinFullName(item)`, `skinFaq(item, t, locale) -> FaqEntry[]` (price, Steam-cheaper, float — **no buy question**), `skinProductLd(item, url) -> ProductLd | null` (single `Offer` in UZS; null without a soʻm price — ruling Q12); `JsonLd` server component.

- [ ] **Step 1: Guard tests first**

```ts
// apps/web/src/app/no-loading-boundaries.test.ts
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe("real 404s", () => {
  it("no loading.tsx anywhere under app/ — a Suspense boundary above a page turns notFound() into a 200", () => {
    const loading = walk(join(__dirname)).filter((p) => /[/\\]loading\.tsx$/.test(p));
    expect(loading).toEqual([]);
  });
});
```

```ts
// apps/web/src/app/[locale]/item/[slug]/page.test.ts
import { describe, expect, it, vi } from "vitest";

const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
vi.mock("next/navigation", () => ({ notFound }));
vi.mock("next-intl/server", () => ({
  getTranslations: async () => Object.assign((k: string) => k, { rich: (k: string) => k }),
  setRequestLocale: () => undefined,
}));
vi.mock("@/lib/skins", () => ({ getSkinDetail: vi.fn().mockResolvedValue(null) }));

import { generateMetadata } from "./page";

describe("unknown item", () => {
  it("metadata calls notFound() too, so status and head agree", async () => {
    await expect(
      generateMetadata({ params: Promise.resolve({ locale: "ru", slug: "nope" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Port components and `skin-seo.ts` (tests first)**

From `yupay:apps/web/src/components/skins/` and `yupay:apps/web/src/lib/skin-seo.ts`, with the Task 13 deltas plus:

- `SkinPriceBlock`: drop the `buyable` prop, the disabled buy button and the «instant delivery» line (decision D3: no buy UI in M2); keep the headline price (`offerHeadline`), the Steam discount badge and the Steam Market link (`rel="nofollow noopener noreferrer"`). Its test drops the buy cases (YuPay lines 81–121).
- `SkinListings`: drop the buy button block and `buyable`; keep float bar, stickers, inspect link, "show more". Its test drops lines 106–143.
- `SkinOffers`: keep `SkinOffersProvider` (one `fetchSkinListings(slug)` in the browser) and `useSkinOffers`; drop select/reprice/drop and `repriceOffer`. `SkinHero` then shows image + exterior badge + the **cheapest** offer's float/stickers/inspect when offers loaded (no selection).
- `SkinWearPicker`: links via `itemPath(slug)`.
- `skin-seo.ts`: drop the buy FAQ entry (`faq.buyQ/buyA` gated on `buy_sku_id`); its test drops those asserts.
- `JsonLd.tsx` from `yupay:apps/web/src/components/JsonLd.tsx` using `serializeJsonLd` from `@csmarket/utils`.

- [ ] **Step 3: The page**

Port `yupay:apps/web/src/app/[locale]/skins/[slug]/page.tsx` to `app/[locale]/item/[slug]/page.tsx`. Deltas:

- `generateMetadata`: `const item = await getSkinDetail(slug); if (!item) notFound();` (not `{}`), title `meta.itemTitle`/`itemTitleNoPrice`, description, `alternates(locale, itemPath(slug))`, OG image `steamImageSize(item.image_url, "512fx384f")`, `robots: ROBOTS`.
- Page: same existence check **first**, before any `<Suspense>`; then the layout without `SkinBuyPanel` and `SkinHowItWorks`; offers section only for `hasWear(category)` items as YuPay does.
- Breadcrumbs: Home → category landing (`categoryPath(item.category)`) or weapon landing for weapon items → item (YuPay linked to a filtered, noindexed hub URL); `BreadcrumbList` JSON-LD carries the same three levels.
- JSON-LD: `skinProductLd(item, localeUrl(locale, itemPath(slug)))` when non-null, `BreadcrumbList`, FAQPage via `SkinFaq`.
- `steamMarketUrl(name)` stays (`https://steamcommunity.com/market/listings/730/<encoded>`).
- No `revalidate` export (fetch revalidates at 60 s); no `generateStaticParams`.

Run: `pnpm --filter @csmarket/web test` → PASS; `NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build` → OK.

- [ ] **Step 4: Commit**

```bash
pnpm exec turbo run lint typecheck --filter=@csmarket/web
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/item): item page with wears, live offers, FAQ and JSON-LD; real 404

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Landings, sitemaps, robots — the catalogue opens to search engines

**Files:**

- Create: `apps/web/src/app/[locale]/category/[category]/page.tsx`, `apps/web/src/app/[locale]/weapon/[weapon]/page.tsx`, `apps/web/src/components/skins/SkinLanding.tsx`, `apps/web/src/lib/skins-sitemap.ts` (+ test), `apps/web/src/app/sitemap.xml/route.ts` (+ test), `apps/web/src/app/skins-sitemap/[file]/route.ts` (+ test), `apps/web/src/lib/skin-landing-copy.test.tsx`
- Modify: `apps/web/src/app/robots.txt/route.ts` (+ `route.test.ts`), `e2e/tests/home.spec.ts` (robots case)
- Test: the route tests above, `skin-landing-copy.test.tsx`, `skins-sitemap.test.ts`, `robots.txt/route.test.ts`

**Interfaces:**

- Consumes: Tasks 11–14 (`fetchSkinSlugs`, `getSkinFacets`, `getSkinsPage`, `landingPaths`, `alternates`, `localeUrl`, paths).
- Produces: landings; `lib/skins-sitemap.ts`: `SKINS_PER_SITEMAP = 5000`, `chunkCount(total)`, `chunkUrl(name)` (`${SITE}/skins-sitemap/<name>.xml`), `today()`, `urlsetXml(paths, lastmod)` (one `<url>` per path × locale with `xhtml:link` alternates for ru/uz/en **and `x-default` → ru** — ruling Q11), `sitemapIndexXml(urls, lastmod)`, `xmlResponse(body)`; `GET /sitemap.xml` (index: `⌈total/5000⌉` chunks + `landings`), `GET /skins-sitemap/<n>.xml` (5000 slugs × 3 locales; empty slice → 404), `GET /skins-sitemap/landings.xml` (home + every category and weapon landing); robots allows crawling.

- [ ] **Step 1: Sitemaps and robots (tests first)**

Port `yupay:apps/web/src/lib/skins-sitemap.ts` + test, `yupay:apps/web/src/app/skins-sitemap.xml/route.ts` → `app/sitemap.xml/route.ts` + test, `yupay:apps/web/src/app/skins-sitemap/[file]/route.ts` + test, `yupay:apps/web/src/app/robots.txt/route.ts` + test. Deltas:

- No `SKINS_ENABLED` anywhere (always on); routes keep `export const dynamic = "force-dynamic"` so `next build` never needs the API, and their fetches revalidate at 3600 s.
- The index lives at `/sitemap.xml` (YuPay's `SKINS_SITEMAP_INDEX` constant goes); item paths are `itemPath(slug)`; landings are `HOME` + `landingPaths(facets)`.
- `urlsetXml` adds `<xhtml:link rel="alternate" hreflang="x-default" href="<ru url>"/>`; extend its test.
- Tests mock `@/lib/server-api` (`apiGet`) instead of YuPay's `@/lib/api`, and drop every `vi.stubEnv("SKINS_ENABLED")`.
- robots: `Host` and `Sitemap: https://csmarket.uz/sitemap.xml` from `SITE`; `Disallow: /api/`, `/account`, `/*/account`, `/auth/`, `/*/auth/`; keep YuPay's `Content-Signal` line and AI-crawler group verbatim (owner policy); drop the `force-static` pre-launch body (decision D2). Test: contains `Allow: /` (or no blanket `Disallow: /`), the sitemap line, and `Disallow: /account`.

Update `e2e/tests/home.spec.ts`: the robots case becomes "robots.txt allows crawling and names the sitemap" (`expect(body).toContain("Sitemap: https://csmarket.uz/sitemap.xml")`, `expect(body).not.toMatch(/^Disallow: \/$/m)`).

- [ ] **Step 2: Landings (tests first)**

Port `yupay:apps/web/src/lib/skin-landing-copy.test.tsx` (ICU counts in ru/uz/en from the real catalogs) and `SkinLanding.tsx`. Port the category and weapon pages from `yupay:apps/web/src/app/[locale]/skins/{category/[category],weapon/[weapon]}/page.tsx`. Deltas:

- Paths `/category/<c>`, `/weapon/<w>`; `allHref` = the home page filtered by that category/weapon (`HOME + skinQueryString(...)`).
- Unknown category (`!isSkinCategory`) or weapon (`findWeapon` null) → `notFound()` in both `generateMetadata` and the page, before any Suspense. An API 404 for facets → `notFound()`; an outage → throws (error page), per ruling Q10.
- `siteName: "csmarket"`, `alternates(locale, path)`, `robots: ROBOTS`, `GEO_META`.
- Knives FAQ entry kept (cheapest knife from live data).

- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/seo): category and weapon landings, sitemaps, robots open

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Admin catalogue page — status, hide an item, search aliases

**Files:**

- Create: `apps/admin/src/features/catalogue/{api.ts, CataloguePage.tsx, StatusCard.tsx, ItemsCard.tsx, AliasesCard.tsx, CataloguePage.test.tsx}`
- Modify: `apps/admin/src/app/router.tsx` (route `/catalogue`), `apps/admin/src/app/Layout.tsx` (nav: «Дашборд», «Каталог»), `apps/admin/src/routes/Dashboard.tsx` (copy: link to the catalogue)
- Test: `apps/admin/src/features/catalogue/CataloguePage.test.tsx`

**Interfaces:**

- Consumes: `session` / `ApiError` / `formatApiError` from `@/lib/api` (M1); admin routes from Task 9 (`GET /api/v1/admin/skins/catalog/status`, `GET /api/v1/admin/skins/items`, `PATCH /api/v1/admin/skins/items/{slug}`, `GET|PUT|DELETE /api/v1/admin/skins/aliases[/{alias}]`).
- Produces: `features/catalogue/api.ts` — types `CatalogStatus`, `JobOut`, `AdminSkinItem`, `Alias` mirroring Task 9's schemas; `getStatus()`, `findItems({ q?, hidden? })`, `setHidden(slug, hidden)`, `listAliases()`, `putAlias(alias, text)`, `deleteAlias(alias)` — every mutation sends a fresh `Idempotency-Key` (`crypto.randomUUID()`), query keys `["catalogue", "status"]`, `["catalogue", "items", q, hidden]`, `["catalogue", "aliases"]`.

Copy is Russian, owner-facing, «вы», short; numbers formatted with `Intl.NumberFormat("ru")`; times as local `HH:MM, DD.MM`.

- [ ] **Step 1: Page test first**

```tsx
// apps/admin/src/features/catalogue/CataloguePage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CataloguePage } from "./CataloguePage";

const api = vi.hoisted(() => ({
  getStatus: vi.fn(),
  findItems: vi.fn(),
  setHidden: vi.fn(),
  listAliases: vi.fn(),
  putAlias: vi.fn(),
  deleteAlias: vi.fn(),
}));
vi.mock("./api", () => api);

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CataloguePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ITEM = {
  slug: "ak-47-redline-ft",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  image_url: null,
  active: true,
  hidden: false,
  price_usd: "10.00",
  count: 5,
};

describe("CataloguePage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getStatus.mockResolvedValue({
      items_total: 35000,
      items_active: 21000,
      items_hidden: 3,
      prices_updated_at: "2026-10-01T10:00:00Z",
      import_job: {
        finished_at: "2026-10-01T03:00:00Z",
        ok: true,
        counters: { files: 11, rows: 35000, changed: 12 },
        error: null,
      },
      price_sync_job: {
        finished_at: "2026-10-01T10:00:00Z",
        ok: false,
        counters: {},
        error: "thin_snapshot",
      },
      fx: { usd_uzs: "12700.0000", fetched_at: "2026-10-01T09:00:00Z", source: "cbu" },
      sync_enabled: true,
      waxpeer_key_set: true,
    });
    api.findItems.mockResolvedValue({ items: [ITEM] });
    api.listAliases.mockResolvedValue({ items: [{ alias: "ак", text: "ak-47" }] });
  });

  it("shows counts, job outcomes and the rate", async () => {
    renderPage();
    expect(await screen.findByText(/21\s000/)).toBeInTheDocument();
    expect(screen.getByText(/Цены не обновились/)).toBeInTheDocument(); // price_sync_job.ok === false
    expect(screen.getByText(/12\s700/)).toBeInTheDocument();
  });

  it("hides an item", async () => {
    api.setHidden.mockResolvedValue({ ...ITEM, hidden: true });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Найти скин"), { target: { value: "redline" } });
    fireEvent.click(await screen.findByRole("button", { name: "Скрыть" }));
    await waitFor(() => expect(api.setHidden).toHaveBeenCalledWith("ak-47-redline-ft", true));
  });

  it("adds an alias", async () => {
    api.putAlias.mockResolvedValue({ alias: "редлайн", text: "redline" });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Как ищут"), { target: { value: "редлайн" } });
    fireEvent.change(screen.getByLabelText("Что найти"), { target: { value: "redline" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    await waitFor(() => expect(api.putAlias).toHaveBeenCalledWith("редлайн", "redline"));
  });
});
```

Run: `pnpm --filter @csmarket/admin test` → FAIL (no page).

- [ ] **Step 2: Build the page**

`CataloguePage` = `PageHeader`-style `h1` «Каталог» + three cards:

- **StatusCard** (`useQuery(["catalogue","status"], getStatus)`): «Скинов в каталоге: N», «В продаже: N», «Скрыто: N»; «Цены обновлены: HH:MM, DD.MM» from `prices_updated_at`; per job a line — ok → «Каталог обновлён HH:MM, DD.MM» / «Цены обновлены …»; not ok → «Каталог не обновился» / «Цены не обновились» + the error label mapped (`thin_snapshot` → «Waxpeer прислал неполный список — цены остались прежними», any other → «ошибка: <label>»); never run → «ещё не запускалось»; «Курс ЦБ: 12 700 сум за $» + time, or «Курса нет — цены показываются в долларах»; when `!sync_enabled || !waxpeer_key_set` a muted line «Обновление цен выключено на этом сервере».
- **ItemsCard**: input labelled «Найти скин» (≥ 2 chars, 300 ms debounce), a «Только скрытые» checkbox (lists `hidden=true` with no `q`); rows: thumbnail (`/128fx96f`), name, category, price, `active` badge («в продаже» / «нет предложений»), and a «Скрыть» / «Показать» button calling `setHidden`; on success invalidate `["catalogue"]`; errors shown with `formatApiError`.
- **AliasesCard**: table alias → text with «Удалить»; a form with inputs «Как ищут» and «Что найти» and «Добавить» (`putAlias`); a hint under it: «Например: ак → ak-47, керамбит → karambit. Поиск заменяет слово целиком.»

Route `{ path: "/catalogue", element: <CataloguePage /> }` inside the `AuthGuard > Layout` branch; Layout gets a small nav (`NavLink` «Дашборд» `/`, «Каталог» `/catalogue`) left of the admin name; Dashboard copy: «Каталог, курс и обновление цен — в разделе «Каталог».» with a link.

- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/admin lint && pnpm --filter @csmarket/admin typecheck
VITE_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/admin build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(admin/catalogue): status, hide an item, search aliases

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: e2e — browse, filter, search, item, real 404s, sitemaps, admin hide

**Files:**

- Create: `e2e/tests/catalogue.spec.ts`, `e2e/tests/admin-catalogue.spec.ts`
- Modify: `e2e/playwright.config.ts` (`web-chromium` testMatch adds `catalogue`; `admin-chromium` adds `admin-catalogue`), `e2e/README.md` (prerequisite: `make seed-skins`), `e2e/tests/helpers.ts` (if a `seeded` helper is useful)

**Interfaces:**

- Consumes: dev stack with `make migrate && make seed-skins` done (Task 10), dev-login (M1), every page and route above.

- [ ] **Step 1: Specs**

```ts
// e2e/tests/catalogue.spec.ts
import { expect, test } from "@playwright/test";

import { API } from "./helpers";

test("the home page is the catalogue, in soʻm", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Скины КС2 (CS2)");
  const cards = page.locator('a[href^="/item/"]');
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThan(10);
  await expect(page.getByText(/сум/).first()).toBeVisible();
});

test("a category filter narrows the grid and is noindex", async ({ page }) => {
  await page.goto("/?category=knives");
  const names = await page.locator('a[href^="/item/"]').allInnerTexts();
  expect(names.length).toBeGreaterThan(0);
  expect(names.every((n) => n.includes("★"))).toBe(true);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});

test("tracking params keep the home page indexable", async ({ page }) => {
  await page.goto("/?utm_source=telegram");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /^index/);
});

test("search suggests and opens an item", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder(/Поиск|Найти/).fill("redline");
  await page
    .getByRole("link", { name: /Redline/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/item\/ak-47-redline/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Redline");
});

test("item page: wears, offers from the snapshot, JSON-LD, no buy button", async ({ page }) => {
  await page.goto("/item/ak-47-redline-field-tested");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("AK-47 | Redline");
  await expect(page.locator('script[type="application/ld+json"]').first()).toBeAttached();
  const ld = await page.locator('script[type="application/ld+json"]').allTextContents();
  expect(
    ld.some((s) => s.includes('"@type":"Product"') && s.includes('"priceCurrency":"UZS"')),
  ).toBe(true);
  expect(ld.some((s) => s.includes('"@type":"BreadcrumbList"'))).toBe(true);
  await expect(page.getByRole("button", { name: /Купить|Buy/ })).toHaveCount(0);
});

for (const path of [
  "/item/no-such-skin-xyz",
  "/category/no-such",
  "/weapon/no-such",
  "/en/item/no-such-skin-xyz",
]) {
  test(`real 404 for ${path}`, async ({ page }) => {
    const response = await page.goto(path);
    expect(response?.status()).toBe(404);
  });
}

test("landings render and link items", async ({ page }) => {
  await page.goto("/category/knives");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ножи КС2");
  await page.goto("/weapon/ak-47");
  await expect(page.locator('a[href^="/item/ak-47-"]').first()).toBeVisible();
});

test("sitemaps: index → chunk → item URLs with alternates", async ({ request }) => {
  const index = await (await request.get("/sitemap.xml")).text();
  expect(index).toContain("<sitemapindex");
  expect(index).toContain("/skins-sitemap/0.xml");
  expect(index).toContain("/skins-sitemap/landings.xml");
  const chunk = await (await request.get("/skins-sitemap/0.xml")).text();
  expect(chunk).toContain("https://csmarket.uz/item/");
  expect(chunk).toContain('hreflang="x-default"');
  expect((await request.get("/skins-sitemap/99.xml")).status()).toBe(404);
});

test("the API answers soʻm and dollars", async ({ request }) => {
  const body = await (await request.get(`${API}/api/v1/skins/catalog?limit=1`)).json();
  expect(body.items[0].price_usd).toMatch(/^\d+\.\d{2}$/);
  expect(body.items[0].price_uzs).toMatch(/^\d+00$/);
});
```

Slugs, headings and placeholders above follow the seeded fixture (Task 10) and the ported copy (Task 12) — open the running pages once and align any literal that differs (the slug format comes from `naming.slug_for`; the knives H1 from `landing.categoryH1`). Keep every assertion's intent.

```ts
// e2e/tests/admin-catalogue.spec.ts
import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

test("an admin hides an item and the storefront 404s it, then shows it again", async ({
  page,
  request,
}) => {
  await devLogin(page, { steamId: "76561198000000882", name: "Owner", admin: true });
  await page.goto("/catalogue");
  await expect(page.getByRole("heading", { name: "Каталог" })).toBeVisible();
  await page.getByLabel("Найти скин").fill("redline field-tested");
  const row = page.getByRole("row", { name: /AK-47 \| Redline \(Field-Tested\)/ });
  await row.getByRole("button", { name: "Скрыть" }).click();
  await expect(row.getByRole("button", { name: "Показать" })).toBeVisible();

  const web = process.env["WEB_BASE_URL"] ?? "http://localhost:3100";
  expect((await request.get(`${web}/item/ak-47-redline-field-tested`)).status()).toBe(404);

  await row.getByRole("button", { name: "Показать" }).click();
  await expect(row.getByRole("button", { name: "Скрыть" })).toBeVisible();
  expect((await request.get(`${web}/item/ak-47-redline-field-tested`)).status()).toBe(200);
});
```

(The web's fetch cache revalidates at 60 s; a hidden item's page may still render from the Next data cache for up to a minute. If the 404 assertion flakes for that reason, make `getSkinDetail` use `revalidate: 0` for `generateMetadata`/page **only when** an admin action needs instant effect — prefer instead `cache: "no-store"` on `getSkinDetail` (item pages are cheap) and say so in the commit body. Decide from the run, not in advance.)

- [ ] **Step 2: Run against the dev stack**

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
make seed-skins
until curl -sf http://127.0.0.1:8100/readyz >/dev/null; do sleep 2; done
until curl -sf -o /dev/null http://127.0.0.1:3100/; do sleep 3; done
make test-e2e
docker compose down
```

Expected: every spec passes (M1 auth/admin specs included). Never touch other containers.

- [ ] **Step 3: Commit**

```bash
npx prettier --check . && pnpm --filter @csmarket/e2e lint && pnpm --filter @csmarket/e2e typecheck
git add -A && git commit -m "test(e2e): browse, filters, item page, real 404s, sitemaps, admin hide

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 18: Docs, ADR-0005, runbook; full verification

**Files:**

- Create: `docs/decisions/0005-skins-catalogue-fx-and-indexing.md`, `docs/runbooks/skins-catalogue.md`, `docs/product/flows/skins-browse.md`, `docs/architecture/sequence-diagrams/skins-price-sync.mmd`
- Modify: `apps/api/src/csmarket/modules/skins/README.md`, `apps/api/src/csmarket/modules/fx/README.md` (if Task 3 left it thin), `apps/api/src/csmarket/modules/admin/README.md`, `docs/architecture/module-map.md`, `docs/architecture/cache-keys.md`, `docs/api/README.md`, `docs/security/pii-handling.md`, `infra/prometheus/alerts/api.yml` (only if the listings route is not yet in the `ApiWaxpeerLatency` handler regex — check `/skins/.+/listings`), `AGENTS.md` (§0 M2 row + status, §11 carve-out wording if needed, §13 `make seed-skins` from Task 10 verified)

- [ ] **Step 1: Write the docs**

- **ADR-0005** (template `docs/decisions/0000-template.md`): context (spec §15 M2; owner decisions D1–D3); decision = rulings Q1–Q13, one short paragraph each, plus the dependencies added in M2 (expect none — say so, or list any with versions); consequences (the catalogue is indexed before sales open; prices fall back to USD without a rate; hidden ≠ deleted; Redis is never required for a page to render); alternatives (YuPay's provider-chain fx; noindex until launch; a public feature flag).
- **skins/README.md**: rewrite for what the module owns now — tables, import, price sync (refusal rule), stored prices, read API, listings carve-out, SEO slugs, admin catalogue, job status, cache keys, dev seed; tests and fixtures.
- **runbooks/skins-catalogue.md**: run the import by hand (`docker compose -f docker-compose.prod.yml exec scheduler python -c "import asyncio; from csmarket_scheduler.jobs.skins_catalog_import import run; asyncio.run(run())"`), same for price sync and fx refresh; what "thin_snapshot" means and what to do; Waxpeer 403 "whitelist your IP" → the VPS IP is not on the account; no rate → USD on the site, check CBU reachability; hiding an item; adding aliases; first launch order (`migrate` → import → price sync → check `/admin` status).
- **flows/skins-browse.md**: Mermaid sequence for visitor → `/` → API catalogue (Redis page cache, Postgres) → item page → listings (cache → budget → Waxpeer → stale → snapshot) and the 404 rule.
- **sequence-diagrams/skins-price-sync.mmd**: scheduler → Waxpeer snapshot stream + `/v1/prices` → refuse-if-thin → lock → apply → reprice → commit → bump version → job status.
- **cache-keys.md**: add `skins:catalog:ver` (no TTL), `skins:{catalog|facets|suggest}:{ver}:{sha1}` (60 s), `skins:pricing` (3600 s), `skins:listings:{slug}` (90 s) and `…:stale` (3600 s), `skins:wax:breaker` (120 s), `skins:wax:budget:{YYYYMMDDHHMM}` (120 s), `skins:job:{import|price_sync}` (no TTL), `fx:usd_uzs` (86 400 s), `auth:ipguard:skins-listings:*` (window). None holds PII.
- **module-map.md**: `skins` built (catalogue, M2; buying M4), `fx` built (rate only; order snapshots M4), `admin` + audit log.
- **api/README.md**: the public skins endpoints (money as strings, `price_uzs` null without a rate, `degraded` on listings, cursor format opaque), admin catalogue endpoints (Idempotency-Key on PATCH/PUT/DELETE).
- **pii-handling.md**: `admin_audit_log` payloads carry slugs/aliases only; Waxpeer API key never logged (query-string key), CBU calls carry nothing personal.
- **AGENTS.md**: §0 M2 row → `docs/superpowers/plans/2026-10-01-m2-skins-catalogue.md`; status paragraph: "M0–M1 merged on local `main`; M2 on branch `m2-skins-catalogue` until the owner says to merge"; §11 already names the listings carve-out — check its numbers match Task 8 (90 s / 1 h / budget 18 / 2-min breaker / 4 s).

- [ ] **Step 2: Full gate**

```bash
git status --porcelain                                   # clean before
make lint typecheck test
cd apps/api && uv run python -m csmarket.scripts.export_openapi /tmp/o.json && cd ../.. && diff -q /tmp/o.json docs/api/openapi.json
docker compose build && docker compose up -d && docker compose exec api alembic upgrade head && make seed-skins
until curl -sf -o /dev/null http://127.0.0.1:3100/; do sleep 3; done
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3100/item/no-such-skin-xyz     # 404
make test-e2e && docker compose down
git status --porcelain                                   # clean after
```

Also confirm a **production** web build serves real 404s (the dev server and the prod server stream differently): `NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 API_INTERNAL_URL=http://localhost:8100 pnpm --filter @csmarket/web build && (cd apps/web && PORT=3199 pnpm start &)` with the dev API up, then `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3199/item/no-such-skin-xyz` → `404`; stop that server by its PID.

Expected: all green; pytest output has no warnings; no OpenAPI drift.

- [ ] **Step 3: Commit**

```bash
npx prettier --check .
git add -A && git commit -m "docs: ADR-0005 catalogue, fx and indexing; skins runbook, flows, cache keys

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

**Spec coverage (§15 M2: "skins tables, ByMykel import, price sync, read API, `/`, `/item`, landings, sitemaps, SEO; admin catalogue page — the catalogue is browsable, no buying"):** tables → T1; import → T5; price sync → T6; pricing seed and stored prices → T2; read API → T7, live listings (§7.3) → T8; `/` → T13; `/item` → T14; landings, sitemaps, robots, SEO copy and JSON-LD → T12, T14, T15; admin catalogue → T9 (API) + T16 (page); soʻm (decision 6, owner D1) → T3 + T7; images (§8) → T1 `images`, T7 rewrite; spec §13 rate limits (listings `ip_guard`) → T8; idempotency on admin writes → T9; admin audit (§13) → T9; §14 hypothesis on pricing → T2, respx contract tests → T3/T4; e2e → T17; docs → T18. Not in M2 by spec: checkout/orders (M4), admin pricing editor (M4), the `/account/orders` and balance pages (M3–M4), static pages `/how-it-works`, `/faq`, `/terms`, `/privacy`, `/contacts` — §10 lists them but §15 does not put them in any milestone before M5; they are left for M5's launch plan (stated here so it is a decision, not an omission).

**Placeholder scan:** no TBD/TODO. Port steps name the source file, the test files and every delta; new code is written out in full.

**Type consistency:** `SkinItemOut` (T7) ↔ `SkinItem` TS type (T11) checked against the generated `openapi.json` in T11 Step 2; `CatalogStatusOut`/`AdminSkinItemOut`/`AliasOut` (T9) ↔ admin `api.ts` types (T16); `usd_uzs_rate(db)` defined in T7 and reused in T8; `current_usd_uzs(db, redis, *, max_age_days)` (T3) used in T7, T9, T10; `record_snapshot(db, *, rate, source)` (T3) used in tests of T7–T9; `refresh_usd_uzs(db, redis, *, fetch, source)` (T3) used in T10; `JOB_IMPORT`/`JOB_PRICE_SYNC`/`record_job`/`read_job` (T5) used in T5, T6, T9; `ApplyResult.refused` (T6) read by the T6 job and shown via `error="thin_snapshot"` in T16; `bump_catalog_version` lives in `cachekeys` (T6) and is used by T6, T9, T10; `hidden` (T1) filtered in T7 service + seo, honoured by T8 (`get_item`), toggled by T9, untouched by T5/T6.

**Review Focus → tests:** 1 → T14 `no-loading-boundaries.test.ts` + `page.test.ts`, T15 landing `notFound()`, T17 e2e 404 statuses, T18 prod-build curl; 2 → T7 `test_skins_catalog_resilience.py`, T8 `test_listings_degrade_without_key`; 3 → T6 `test_a_collapsed_snapshot_is_refused` (+ `refused`), T4 contract tests (429, missing columns); 4 → T9 `test_hide_hides_everywhere_and_unhide_restores` + T17 admin e2e; 5 → T13 `metadata.test.ts` + T17 e2e robots meta.
