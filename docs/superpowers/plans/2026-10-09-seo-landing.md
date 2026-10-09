# SEO landing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (owner: inline, no subagents). Steps use checkbox (`- [ ]`) syntax.

**Goal:** the approved landing at `/` (ru, `/uz`, `/en`), the catalogue at `/market`, old filtered root URLs 301 to `/market`, geo-SEO metadata and JSON-LD.

**Architecture:** Next 15 App Router server components read the public catalogue API through `lib/skins.ts` (cached 300 s); a small `lib/landing.ts` composes the hero, popular tabs, stats and category tiles from ordinary catalogue queries (no API change). Middleware redirects filtered root URLs before next-intl.

**Tech Stack:** Next 15, next-intl 4, Tailwind v4, `@csmarket/ui`, Vitest + Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-09-seo-landing-design.md`; mockup `docs/design/landing-hifi.html`.

## Global Constraints

- ru / uz (Latin) / en strings for every visible word, under `web.landing.*`; the i18n parity test passes.
- Copy rules AGENTS.md §12; no fake reviews or figures; reviews block hidden.
- One H1 per page; JSON-LD `Organization`, `WebSite`+`SearchAction`, `FAQPage` (visible FAQ only).
- Server components by default; client only for the hero rotation, popular tabs, FAQ toggles if needed, the mobile SEO-text fold.
- `prefers-reduced-motion` disables motion. Indexing stays closed.
- Files ≤ 300 LOC (TS); no `any`; TS strict.

## Review Focus

1. A filtered root URL with tracking params (`/?utm_source=x&category=knives`) must still 301 to `/market` (catalogue key wins).
2. The catalogue API down: the landing must still render (hero/popular empty states), not 500.
3. Hero items out of stock: skipped; fewer than 3 → fallback to dearest knives.
4. `/uz` landing must be fully Uzbek (no Russian leaks) — parity + a render test.
5. Internal catalogue links must point at `/market` (header, menus, breadcrumbs, empty states, sitemap).

---

### Task 1: Move the catalogue to `/market`, redirects, links, sitemap

- Move `app/[locale]/page.tsx` (+ tests, loading) to `app/[locale]/market/`; metadata `alternates(locale, MARKET)`.
- `lib/paths.ts`: `MARKET = "/market"`; switch every catalogue link (`grep -rn "HOME" apps/web/src`).
- `middleware.ts`: locale root + catalogue query key → 301 `/market` (+locale prefix), query kept; test file `middleware.test.ts`.
- Sitemap route: add `/market` per locale.
- Tests: middleware cases (spec §7), paths, metadata of `/market`.
- Commit `feat(web): the catalogue moves to /market; filtered root URLs redirect there`.

### Task 2: Landing data (`lib/landing.ts`)

- `HERO_QUERIES` (curated: Karambit Fade, Sport Gloves Vice, AK-47 Fire Serpent, M9 Bayonet Gamma Doppler, AWP Asiimov) → one catalogue query each (`q`, category, sort popular, limit 1); skip empty; fallback dearest knives when < 3.
- `getPopular(tab)`: `popular` interleaves knives / gloves / rifles / pistols / snipers popular pages to 12; `knives`, `gloves`, `cheap` (max 100 000 сум) use filters.
- `getCategoryTiles()`: facets → per category the popular top item image + lowest price (sort price asc, limit 1).
- `getStats()`: total in stock (sum of category facets), lowest price.
- Every call guarded: an API failure returns empty data (landing still renders).
- Unit tests with mocked fetch.

### Task 3: Landing components, copy, metadata, JSON-LD

- `components/landing/*` per spec §6, visual per the mockup (tokens, slanted markers, rarity glow).
- `app/[locale]/page.tsx` = landing; `generateMetadata` titles/descriptions per locale, `alternates(locale, HOME)`, `GEO_META`, OG.
- JSON-LD via `components/JsonLd.tsx`.
- i18n `web.landing.*` ru/uz/en incl. FAQ and ~700-word SEO text.
- Tests: render (H1, sections, no reviews, search action, FAQ JSON-LD equals visible FAQ), uz render has no Cyrillic in landing copy.
- Commit `feat(web/landing): the SEO landing at the root`.

### Task 4: E2E, docs, checks

- `e2e/tests/landing.spec.ts` (spec §7 E2E).
- Docs: `docs/runbooks/indexing.md` note, web README/sitemap notes, AGENTS.md §0 line.
- `make lint typecheck` for web, vitest web + i18n, prettier, visual check at 1440/390, Lighthouse numbers.
- Commit `docs(web): the landing and /market`.
