# Search indexing — closed until the owner opens it

The storefront (`csmarket.uz`) is kept out of search engines until the owner says it is ready
(owner, 2026-10-06). The switch is one variable at the edge, in Caddy — not in Next, which
prerenders some pages at build time and would need a rebuild.

| `CSMARKET_INDEXING` in `secrets/caddy.env` | What crawlers get                                                                                        |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| missing, `off`, anything but `on`          | `robots.txt` = `User-agent: *` / `Disallow: /`; every response carries `X-Robots-Tag: noindex, nofollow` |
| `on`                                       | the storefront's own `robots.txt` (sitemaps, Content-Signal) and no `X-Robots-Tag`                       |

`admin.`, `api.` and `grafana.` always send `X-Robots-Tag: noindex, nofollow`, whatever the
switch says. Config: the `INDEXING GATE` block in `infra/caddy/Caddyfile.prod`.

## What gets indexed

- `/`, `/uz`, `/en` — the SEO landing (spec `2026-10-09-seo-landing-design.md`): the geo H1,
  FAQ (`FAQPage`), `Organization` and `WebSite` (`SearchAction` → `/market?q=`) JSON-LD.
- `/market` (+ `/uz/market`, `/en/market`) — the catalogue; filtered views are `noindex, follow`.
  Old filtered root URLs (`/?category=knives`) answer **301** to `/market` with the query kept.
- `/item/…` — `Product` + `Offer` in UZS, breadcrumbs, «О предмете» (a paragraph from the item's
  facts), «Другие скины <weapon>» (internal links), FAQ with price, dated Steam comparison, float,
  payment and the 7-day trade hold; `/category/…`, `/weapon/…` — breadcrumbs and
  an `ItemList` of the shown skins (the unfiltered `/market` carries one too).
- Query landings: `/pay/click`, `/pay/payme`, `/pay/uzum` («скины КС2 через Click …»: steps,
  popular skins, FAQ) and `/cheap` (weapon skins under 100 000 soʻm, live answers). Category
  pages answer price and how-to-buy questions (`FAQPage`) from live numbers; knives, gloves,
  rifles, pistols, cases and agents carry a paragraph of text. All are in `landings.xml` and in
  the landing's footer.
- Share previews: the landing, `/market`, categories and weapons use `public/og/<locale>.jpg`
  (1200×630, from `docs/design/og.html`). Item pages get a generated card,
  `/<locale>/item/<slug>/og.png` (`app/[locale]/item/[slug]/og.png/route.tsx`, `next/og`):
  the logo, the weapon over the skin name, StatTrak™ / Souvenir / phase / wear, the skin on the
  right in its rarity glow, no price. IBM Plex Sans is read from the repo (`apps/web/assets/og`,
  once per process; on failure the built-in font); a Steam picture that fails leaves the card without it;
  an API outage redirects to `/og/<locale>.jpg`. Cached a day (`s-maxage`, Cloudflare). Telegram
  keeps a link's preview: after a design change send the URL to @WebpageBot to refresh it.
- `/llms.txt` — the shop for language models, with live category counts; the partner API has
  its own at `docs.csmarket.uz/llms.txt`. It is served (with `X-Robots-Tag: noindex`) while
  indexing is closed.
- `/sell`, `/steam`, `/reviews` are `noindex` on purpose and stay out of the sitemaps.
- Before opening: add csmarket.uz to Google Search Console and Yandex Webmaster (region
  Uzbekistan) and submit `https://csmarket.uz/sitemap.xml`.

## Open indexing (only on the owner's word)

```bash
ssh <deploy-user>@<vps>
cd ~/opt/csmarket
sed -i 's/^CSMARKET_INDEXING=.*/CSMARKET_INDEXING=on/' secrets/caddy.env
grep CSMARKET_INDEXING secrets/caddy.env        # CSMARKET_INDEXING=on
docker compose -f docker-compose.prod.yml up -d --force-recreate caddy
```

Check from outside:

```bash
curl -sI https://csmarket.uz/ | grep -i x-robots-tag   # nothing
curl -s https://csmarket.uz/robots.txt | head -3       # User-Agent: * / Allow: / …
```

Then submit `https://csmarket.uz/sitemap.xml` in Google Search Console and Yandex Webmaster.

## Close it again

Same steps with `CSMARKET_INDEXING=off`. Pages already in the index drop out as crawlers
revisit them and see `noindex` (days to weeks); for an urgent removal use the search
consoles' removal tools.

## Cloudflare

- **After a flip, purge everything** (Caching → Configuration → Purge Everything). Static files
  (`/og/*.jpg`, `/_next/static/*`) sit in Cloudflare's cache with the header they were served with,
  `X-Robots-Tag: noindex` included, until they expire. The closed `robots.txt` itself is sent with
  `Cache-Control: no-store`; the open one is cached an hour.
- **Bot settings** (Security → Bots, AI Crawl Control): «Block AI bots» off, AI crawlers allowed,
  «Bot Fight Mode» off, **«Manage robots.txt» / «Bot Preference Sync» off** — it would prepend
  Cloudflare's own rules to ours. `robots.txt` is the storefront's alone (`apps/web/src/app/robots.txt`).

## After opening

1. Google Search Console: add the **domain** property `csmarket.uz` (DNS TXT record in Cloudflare),
   submit `https://csmarket.uz/sitemap.xml`, inspect `/`, `/market` and one item URL.
2. Yandex Webmaster: add `https://csmarket.uz`, verify (meta tag or DNS), submit the sitemap, set
   the region to **Uzbekistan** («Региональность»), check «Clean-param» is read under
   «Анализ robots.txt».
3. A week later: Search Console → Pages: «Discovered — not indexed» and soft 404s;
   Yandex → «Страницы в поиске» → excluded pages.

## What crawlers and assistants are told

- `robots.txt`: everything but `/api/`, the account and the sign-in callback; Yandex's
  `Clean-param` for ad tags and the catalogue's `sort` / `cursor`; AI crawlers (GPTBot, ClaudeBot,
  PerplexityBot, …) welcome with `Content-Signal: search=yes, ai-input=yes, ai-train=no`.
- Out of the index on purpose (`noindex, follow`): filtered and searched `/market` views, item pages
  with nothing in stock (back once stocked), category and weapon pages with fewer than 10 items
  (`MIN_LANDING_ITEMS`, also left out of `landings.xml`), `/sell`, `/steam`, `/reviews`.
- `/llms.txt`: the shop, sections with live counts, buying by payment method, how delivery and
  refunds work (as the terms say), the legal documents.
- **Markdown for agents** (2026-10-13): a request that asks for `text/markdown` above `text/html`
  (`Accept: text/markdown`) to the home page, `/market`, a category, a weapon or an item page —
  any locale — gets the page's Markdown twin at the same URL (`middleware.ts` → `app/md`,
  `lib/agent-md*.ts`): the same headings, live prices, item links and FAQ as the HTML. Browsers
  and search crawlers (`text/html`, `*/*`) get the HTML as before. The twin is `no-store`,
  `Vary: Accept`, `X-Robots-Tag: noindex`; `/md/…` opened directly is a 404. Check it:
  `curl -H "Accept: text/markdown" https://csmarket.uz/item/ak-47-redline-field-tested`. This is
  our own version of Cloudflare's «Markdown for Agents» (a Pro-plan switch, not used).
