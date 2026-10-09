# SEO landing at the root, the market at /market — design

- **Status:** draft for the owner's review (2026-10-09). The owner approved the hi-fi mockup
  `docs/design/landing-hifi.html` («очень круто получилось, делаем»).
- **Why:** the root of csmarket.uz is today the catalogue. Search traffic in Uzbekistan goes to
  queries with a local modifier («скины кс2 узбекистан», «в сумах», «Click / Payme / Uzum»,
  «cs2 skin sotib olish») that no international market targets and the local one (skinsavdo.uz)
  serves poorly (Russian only, no hreflang, no structured data, no sitemap). A landing at the
  root built for those queries, in ru / uz / en, with the market one click away, is the first of
  four SEO sub-projects.
- **Research:** competitor reports (lis-skins, market.csgo, cs.money, waxpeer, skinport, dmarket,
  skinsavdo.uz and the Uzbek SERP) are summarised in §8.
- **Not here (later sub-projects):** title/description templates with soʻm prices on item pages,
  `Product`/`AggregateOffer` JSON-LD review, `x-default` / `ru-UZ` hreflang review, robots for
  filter params, split sitemaps, `llms.txt` (sub-project 2); query landings — «купить скины КС2 в
  Узбекистане», Click / Payme / Uzum pages, knives, gloves, cases (sub-project 3); guides,
  glossary, blog (sub-project 4).

## 1. Success

1. `/`, `/uz`, `/en` show the landing of the mockup, server-rendered, with real skins and prices.
2. The catalogue lives at `/market` (`/uz/market`, `/en/market`) and behaves exactly as `/` does
   today (filters, sort, search, infinite grid, noindex on filtered views).
3. Every old filtered root URL (`/?category=knives`, `/?q=…`, `/uz?sort=…`) answers **301** to the
   same query on `/market`; a plain `/` with tracking params only (`utm_*`, `gclid`, `fbclid`)
   stays on the landing.
4. Every internal link that meant «the catalogue» points to `/market`: the header «Маркет», the
   logo stays on `/`, category / weapon menus, item breadcrumbs, «Весь маркет», empty states.
5. Lighthouse on the landing (mobile): Performance ≥ 85, SEO 100, Accessibility ≥ 95; LCP image
   is the hero skin, preloaded.
6. Indexing stays closed (`CSMARKET_INDEXING=off`) until the owner opens it; nothing here opens it.

## 2. Decisions

1. **Locales:** the same routing as today (`localePrefix: "as-needed"`: ru at the root, `/uz`,
   `/en`). The landing is written for all three; the Uzbek copy is Latin script, written as
   native copy, not a word-for-word translation.
2. **Item pages stay at `/item/<slug>`**, category and weapon pages at `/category/…`,
   `/weapon/…` — no URL churn for pages that already exist. The mockup's `/market/<slug>` links
   become `/item/<slug>`.
3. **No fake data.** The reviews block of the mockup ships **hidden** until a real source exists
   (`/reviews` is still «Скоро»); stats show only what the catalogue backs (count of skins in
   stock, the lowest price, «3 способа оплаты в сумах», «поддержка RU · UZ»). The sell block
   shows illustrative cards without sums (the real sums live on `/sell`).
4. **Hero showcase is curated:** a short list of slugs in config
   (`apps/web/src/lib/landing.ts`, `HERO_SLUGS`, 5 items: a knife, gloves, two rifles, an AWP),
   each read from the catalogue for its live price and image; an item not in stock is skipped,
   and if fewer than 3 remain the hero falls back to the most expensive in-stock knives.
5. **Popular tabs:** «Популярное» excludes cases, keys and charms (weapon skins, knives,
   gloves, agents only); «Ножи», «Перчатки», «До 100 000 сум» use the catalogue's own filters.
   12 items each, server-rendered for the first tab, the others fetched on click.
6. **Data path:** the landing reads the public catalogue API server-side (`lib/skins.ts`
   helpers, same caching as the market: revalidate 300 s); no new API endpoint is needed unless
   the catalogue cannot express «exclude categories» — then one query param is added
   (`exclude_category`, repeated), with a test.
7. **Images:** Steam CDN images go through the same image path the market uses (`next/image`
   or our image endpoint, whichever the market uses today), sized per slot; the hero image is
   `priority`.
8. **Motion** as in the mockup (hero rotation every 6 s, pause on hover, hover lifts, fade-in on
   scroll), all off under `prefers-reduced-motion`. The hero rotation is a client component; the
   rest of the page is server components.
9. **Search box** submits to `/market?q=…` (a GET form, works without JS); the «Часто ищут»
   chips are links to `/market?q=…`.
10. **Copy rules** (AGENTS.md §12) apply: short sentences, «вы», outcome not mechanism, never
    «всегда дешевле», «КС2 (CS2)» in RU titles, skin names in English.

## 3. Page structure (from the mockup)

| #   | Section          | Content                                                                                                                    | Notes                      |
| --- | ---------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| 1   | Header           | the live header, «Маркет» → `/market`                                                                                      | unchanged component        |
| 2   | Hero             | H1 «Скины КС2 (CS2) в Узбекистане», lead, «Открыть маркет» + «Продать скины», payment chips; showcase stage + 5 thumbnails | one H1 per page            |
| 3   | Search           | large search, «Часто ищут» chips                                                                                           | GET → `/market`            |
| 4   | Popular          | tabs + 12 cards                                                                                                            | `SkinCard` reused          |
| 5   | Stats            | 4 backed figures                                                                                                           | numbers from the catalogue |
| 6   | Categories       | 2 large (knives, gloves) + 8 small tiles with a real skin and «от N сум»                                                   | links to `/category/<c>`   |
| 7   | Buy & sell       | «Купить скин — три шага», «Продайте скины — получите сумы»                                                                 | sell links to `/sell`      |
| 8   | Why us           | 4 guarantees + Telegram button                                                                                             | Telegram URL from config   |
| 9   | Reviews          | hidden until real data (decision 3)                                                                                        | —                          |
| 10  | FAQ              | 7 questions, `<details>`                                                                                                   | FAQPage JSON-LD            |
| 11  | About (SEO text) | ~700 words in 8 blocks, two columns on desktop, folded on mobile with «Читать полностью» (full text in the HTML)           | H2/H3 inside               |
| 12  | Final CTA        | «Ваш следующий скин — в пару кликов»                                                                                       | → `/market`                |
| 13  | Footer           | the live footer                                                                                                            | unchanged                  |

## 4. SEO of the landing

- `<title>` and description per locale, e.g. RU «Скины КС2 (CS2) в Узбекистане — купить за сумы
  через Click, Payme, Uzum | csmarket», UZ «CS2 skinlari Oʻzbekistonda — soʻmda sotib oling |
  csmarket», EN «CS2 skins in Uzbekistan — pay in soʻm | csmarket».
- `alternates` as today (`lib/seo.ts`), canonical to the clean locale root; `GEO_META` kept.
- JSON-LD: `Organization` (name, url, logo, sameAs: Telegram/Instagram from config),
  `WebSite` with `SearchAction` (`/market?q={search_term_string}`), `FAQPage` (the visible FAQ
  only).
- Internal links: categories, top weapons (AK-47, AWP, M4A1-S, Desert Eagle, Glock-18), `/sell`,
  `/market`.
- The sitemap lists `/` and `/market` per locale with hreflang alternates (the existing sitemap
  route gains `/market`).
- `/market`'s own title/description move from today's root metadata («Маркет скинов КС2 (CS2)…»);
  its filtered views stay `noindex, follow`.

## 5. Routing changes

- `app/[locale]/page.tsx` → the landing; the catalogue page moves to
  `app/[locale]/market/page.tsx` (+ its `loading.tsx` / tests).
- `lib/paths.ts`: `HOME = "/"` stays for the landing; a new `MARKET = "/market"`; every catalogue
  link switches to `MARKET` (header nav, `SkinCategoryBar`, `SkinFilters`, `SkinSort`,
  `SkinSearch`, `SkinGridMore`, `SkinPriceFilter`, `WeaponMenu`, `OtherCategoriesMenu`, item
  breadcrumbs, `ComingSoon`, `TradesView` empty state, skins sitemap).
- `middleware.ts`: a request to a locale root (`/`, `/uz`, `/en`) whose query has a recognised
  catalogue key (`parseSkinQuery` / `isFilteredQuery`, plus `q`, `sort`, `page`) → **301** to the
  locale's `/market` with the query kept. Tracking params alone do not redirect.
- Caddy needs no change (the web app owns both paths).

## 6. Components

- `components/landing/*`: `Hero` (server shell) + `HeroShowcase` (client: rotation),
  `LandingSearch`, `PopularTabs` (client for tab switching; first tab server-rendered),
  `StatsStrip`, `CategoryTiles`, `BuySell`, `WhyUs`, `Faq`, `AboutText` (with the mobile fold),
  `FinalCta`. Each ≤ 300 LOC, composed from `@csmarket/ui` and the tokens.
- New reusable bits go to `packages/ui` only if the market can use them too (e.g. a section
  header with the slanted marker); otherwise they stay in `apps/web`.
- All strings in `packages/i18n/locales/{ru,uz,en}/web.json` under `landing.*` (the SEO text
  included); the parity test must pass.

## 7. Testing

- Unit (Vitest): the landing renders H1, sections, FAQ; JSON-LD has `Organization`, `WebSite`
  with `SearchAction`, `FAQPage` matching the visible FAQ; reviews block absent; hero skips
  out-of-stock slugs and falls back; popular «Популярное» excludes cases; search form action is
  `/market`.
- Middleware tests: `/?category=knives` → 301 `/market?category=knives`; `/uz?q=ak` → 301
  `/uz/market?q=ak`; `/?utm_source=x` → 200 landing; `/market?…` untouched.
- Metadata tests: titles/descriptions per locale, alternates, canonical; `/market` keeps
  `noindex` on filtered views.
- Link audit test: no catalogue link points at `/` (grep-style test over the nav/menu helpers).
- E2E (Playwright, dev stack): landing loads with real cards; search → `/market?q=`; header
  «Маркет» → `/market`; an old `/?category=knives` lands on `/market?category=knives`.
- Lighthouse run on the dev build (manual, numbers in the PR).

## 8. Research summary (2026-10-09)

- **cs.money:** a true landing (hero, value props, FAQ, «О сайте» ~3k chars, popular skins);
  item pages ~2.5k chars + FAQ; ru-uz hreflang maps Uzbekistan to `/ru/`.
- **skinport:** landing at `/`, market at `/market`, ~2 100 words of SEO text under 9 H2s,
  14 languages, wiki, «sell CS2 skins» landings.
- **lis-skins:** many single-query landings (`/cs2/`, payment-method pages, cases), heavy social
  proof (22 987 reviews), ~1 700 blog posts.
- **waxpeer:** item titles with price («— from $26.33»), category pages with ~330 words of live
  text, `llms.txt`, AI bots allowed.
- **dmarket:** volume — a 13.6k-page wiki and a 700-post blog.
- **skinsavdo.uz:** RU only, `lang="en"`, no hreflang / canonical / JSON-LD / sitemap; pays via
  Humo, Uzcard, Visa — not Click, Payme, Uzum.
- **Uzbek SERP:** international markets hold the generic RU queries; the local modifiers
  (Узбекистан, сум, Click/Payme/Uzum) and Uzbek-language queries are open; only casex.uz does
  Uzbek SEO. Demand figures are estimates until keyword data (Ahrefs / Wordstat / Keyword
  Planner / Search Console) is available.

## 9. Owner tasks (outside the code)

- Google Search Console and Yandex Webmaster for csmarket.uz (region: Uzbekistan) — before
  indexing opens, so data accrues from day one.
- Telegram and Instagram links for the footer and `Organization.sameAs`.
- Real reviews (a source for the reviews block) and, later, keyword data.

## 10. Delivery

One plan, one branch (`seo-landing`), merged into local `main`; push and deploy on the owner's
word. Indexing stays closed.

## Revision 2026-10-09 — the owner's review of the first build

- **Hero:** the rotating single-skin stage is replaced by a wall of real, clickable skin cards —
  three columns drifting in opposite directions on a slightly tilted plane (pure CSS; pauses on
  hover / focus, still for reduced motion, two columns on phones). Cards come from the curated
  showcase, then knives, gloves and popular skins in turn (`wallItems`, 18 cards).
- **Payments:** the providers' own logos (Click, Payme, Uzum, copied from YuPay into
  `public/pay/`) replace the text wordmarks; the hero row no longer lists the balance.
- **Search block removed** (§3 row 3). Its weapon links move to a footer «Оружие» column, so
  the `/weapon/<slug>` pages keep an internal link from the root.
- **Categories:** the category icon is white, left of the name; a «Весь каталог» tile with the
  catalogue count closes a short last row.
- **Buy panel** walks one real skin: picked → paid with Click (the price to pay) → the Steam
  trade offer for that skin with «Принять».
- **Sell panel** shows six everyday skins with their market prices, three picked, the sum, and
  the payout choice (balance, Uzcard, Humo, Uzum Visa); the copy says the sum goes to Uzcard,
  Humo or Uzum Visa. The prices are an illustration of the sell page, not a quote.
