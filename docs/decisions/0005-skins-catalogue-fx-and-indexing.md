# 0005. Skins catalogue, the soʻm rate and open indexing (M2)

- **Status**: Accepted
- **Date**: 2026-10-01
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data | infra

## Context and problem statement

M2 (spec §15) makes the catalogue browsable: tables, the ByMykel import, the Waxpeer price
sync, the read API, `/`, `/item`, landings, sitemaps and an admin catalogue page. There is no
buying yet. During planning the owner took three decisions that go beyond the spec text:

- **D1.** The CBU USD/UZS rate moves into M2: the catalogue shows soʻm from the first day.
- **D2.** The catalogue is open to search engines from the M2 deploy (robots allow, sitemaps
  served), so it is indexed before sales open.
- **D3.** The item page has no buy button or buy panel in M2: price and live offers only.

Planning then settled thirteen smaller questions (Q1–Q13), and execution added a few more.
This ADR records them so M3 and M4 do not have to rediscover them.

## Decision drivers

- Parity with the market leader needs a catalogue that search engines already know at launch.
- Waxpeer is the only supply, its key works only from the VPS IP, and its rate limit is 20
  calls a minute: the read path must not depend on it.
- YuPay's code is ported by allow-list (ADR-0002); where YuPay served another product, it is
  trimmed rather than carried.
- A page must render when Redis, Waxpeer or the rate is missing.

## Considered options

1. **Port YuPay's provider-chain fx and keep its `cs2_skins_enabled` flag.** Familiar, but
   2 600 lines for a rate CBU publishes daily, and a flag for the product itself.
2. **Keep the site `noindex` until sales open.** Safe, but the catalogue would start
   indexing only at M4 and lose weeks of ranking.
3. **A small `fx` module, an always-on read API, open indexing from M2** (chosen).

## Decision outcome

**Chosen option:** 3, with the rulings below.

- **Q1 — No public feature flag.** Skins are the product; the read API is always on.
  `CSMARKET_SKINS_SYNC_ENABLED` (default `false`, `true` in prod secrets) gates only the
  scheduler's import and price sync. `CSMARKET_SKINS_CATEGORIES` keeps the visible-category
  allow-list.
- **Q2 — Pricing drops the B2B channel.** Retail brackets, expenses, liquidity, category and
  weapon points, min margin, floor, rounding and Steam cap stay as tuned in YuPay; the
  merchant channel (`b2b`, `extra_pp`) has no counterpart here.
- **Q3 — `fx` is new and small.** `fx_snapshots`, a CBU fetch, Redis `fx:usd_uzs`,
  `current_usd_uzs()`. An hourly job inserts a snapshot when the rate changed or the last one
  is 20 h old. A snapshot older than 7 days counts as no rate: prices then show in dollars and
  soʻm filters are ignored. M4 orders will point at `fx_snapshots.id`.
- **Q4 — Hidden is not deleted.** `skin_items.hidden` removes an item from the catalogue,
  facets, suggest, sitemap and family lists, and `GET /skins/{slug}` answers 404. The price
  sync still prices it, so unhiding is instant.
- **Q5 — `admin_audit_log` arrives now.** Hiding an item and editing aliases are the first
  admin actions. Payloads name things (slugs, aliases), never people.
- **Q6 — Job status lives in Redis** (`skins:job:{import|price_sync}`, no TTL), written by the
  scheduler, read by the admin status card. No table, no "run now" button: the runbook has the
  command.
- **Q7 — Dev and e2e data without Waxpeer.** `seed_skins_dev` loads a committed fixture of
  about 60 items through the real `apply_prices` and `reprice_rows` and a `source='dev'` rate;
  it refuses to run in prod.
- **Q8 — Shared TS lives in `@csmarket/utils`** (`packages/utils/src/skins/*`, exported as
  `@csmarket/utils/skins`).
- **Q9 — Indexability on `/`.** Any recognised filter parameter makes the page
  `noindex,follow` with canonical `/`; tracking parameters (`utm_*`, `fbclid`, `gclid`) do not.
- **Q10 — An outage is not a 404.** Web data helpers return `null` only on an API 404 and
  throw otherwise; the home page never calls `notFound()`.
- **Q11 — Sitemap alternates include `x-default` → ru**, matching the pages' `hreflang` links.
- **Q12 — JSON-LD:** `Product` with one `Offer` in UZS, only when a soʻm price exists;
  `BreadcrumbList`; `FAQPage`.
- **Q13 — Search aliases are admin-edited, none seeded.** An alias substitutes whole words,
  so a one-word alias is what matches.

Decisions taken during execution:

- **No payment-provider names in indexed copy until M3.** Titles, descriptions and intros say
  «за сумы» and the delivery outcome; Click, Payme and Uzum come back with the kassas.
  Snippets must not advertise payments that do not exist yet (D2 with D3).
- **RU landing H1s carry «(CS2)»** («Ножи КС2 (CS2)», «Скины {weapon} КС2 (CS2)»): the spec §10
  title rule beats the ported copy.
- **Item pages are fetched no-store.** An admin hide must 404 the item page at once; the
  grid, suggest and facets may show it for up to 60 s (web data cache) and the sitemap for up
  to 1 h.
- **`search_listings` returns a name → listings mapping** (YuPay's shape), so the listings
  service reads one name out of it.
- **Listing ids may reach the browser.** An opaque numeric offer id is not branding, and the
  M4 checkout needs `{item_id, offer_id}` (spec §7.4).
- **The page-cache key includes the soʻm rate**, so a new CBU rate does not serve old soʻm
  prices from a 60 s page.

**Dependencies added in M2:** none. (`hypothesis` was already a dev dependency; the only
package change is `packages/utils` exporting the `./skins` entry.)

### Positive consequences

- The catalogue is indexed before sales open.
- Nothing on the read path needs Waxpeer; `GET /skins/{slug}/listings` degrades to the
  5-minute snapshot with `degraded: true`.
- Redis is never required for a page to render: every cache error falls through to Postgres.
- A bad price snapshot cannot sell-out the catalogue: a snapshot naming under half of the
  active items is refused and the previous prices stand.

### Negative consequences

- A missing or stale rate makes the whole site show dollars until CBU answers again.
- The catalogue shows prices before the shop can sell anything; D3 keeps copy free of buying
  language, and M4 must add the buy panel and recheck the copy.
- A hide takes up to 60 s to leave the grid and up to 1 h to leave the sitemap.

## Validation

- The gate for M2: `make lint typecheck test`, no OpenAPI drift, e2e on the dev stack, and a
  production web build that answers a real HTTP 404 for an unknown item.
- After the deploy: Search Console shows the sitemap index read; `/admin` shows a recent
  price tick and a CBU rate (`docs/runbooks/skins-catalogue.md`).

## Alternatives considered (detail)

### YuPay's provider-chain fx

Multi-provider with admin overrides. Over-built for one daily CBU number, and its manual
override has no consumer before M3. Rejected; M3 may add an override if the owner asks.

### `noindex` until launch

Removes the risk of showing prices that cannot be bought. Costs the ranking weeks before M4;
the owner chose indexing (D2) and the copy rule above covers the risk.

### A public feature flag for the catalogue

YuPay's `cs2_skins_enabled`. Here the catalogue is the product, and a flag would make "the
site is up but empty" a valid state. Rejected (Q1).

## References

- Spec §5, §7.3, §10, §15; plan `docs/superpowers/plans/2026-10-01-m2-skins-catalogue.md`
- [ADR-0002](./0002-port-from-yupay-by-allowlist.md), [ADR-0004](./0004-steam-auth-and-sessions.md)
- Runbook: [`skins-catalogue.md`](../runbooks/skins-catalogue.md); flow:
  [`skins-browse.md`](../product/flows/skins-browse.md)
