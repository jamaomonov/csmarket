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
- `/item/…` — `Product` + `Offer` in UZS, breadcrumbs; `/category/…`, `/weapon/…` — breadcrumbs and
  an `ItemList` of the shown skins (the unfiltered `/market` carries one too).
- Share previews: the landing, `/market`, categories and weapons use `public/og/<locale>.jpg`
  (1200×630, from `docs/design/og.html`); item pages use the skin's own picture.
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

Cloudflare's cache may hold `robots.txt` for up to an hour (`max-age=3600`). After a flip,
purge `https://csmarket.uz/robots.txt` in the Cloudflare dashboard (Caching → Purge by URL).
