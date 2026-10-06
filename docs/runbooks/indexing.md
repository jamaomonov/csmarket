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
