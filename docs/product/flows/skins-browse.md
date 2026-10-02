# Flow — Browse the catalogue and open an item

A visitor needs no account to browse (M2). There is no buy button yet: the item page shows
the price and the live offers (owner decision D3). The catalogue is open to search engines
(D2).

## What the visitor sees

1. `/` is the catalogue: categories, filters, search, a grid sorted by price (highest first
   by default). Prices are in soʻm. If no rate is available the prices show in dollars.
2. Typing in the search box suggests items; an admin-defined alias («ак») finds «AK-47».
3. A card opens the item page: the image, the price from, the wears and StatTrak / Souvenir
   variants, the live offers (seller, float, stickers, inspect link) and a short FAQ.
4. Category and weapon landing pages (`/category/knives`, `/weapon/ak-47`) list the same items
   with their own title and text.
5. An unknown or hidden item, category or weapon is a real 404 page.
6. If the live offers cannot be fetched right now, the page shows the last known cheapest
   offers; it never shows an error for that.

## Sequence

```mermaid
sequenceDiagram
    autonumber
    actor V as Visitor
    participant Web as Storefront (Next.js)
    participant API as API
    participant R as Redis
    participant DB as Postgres
    participant WP as Waxpeer

    V->>Web: GET /
    Web->>API: GET /skins/catalog?sort=-price (data cache 60 s)
    API->>R: GET skins:catalog:{ver}:{sha1(query, rate)}
    alt page cached
        R-->>API: JSON body
    else miss or Redis down
        API->>DB: filtered, keyset-paged read (no hidden, enabled categories)
        API->>R: SET page, 60 s (errors swallowed)
    end
    API-->>Web: items with price_usd and price_uzs (null without a rate)
    Web-->>V: HTML (indexable, any filter param makes it noindex)

    V->>Web: GET /item/{slug}
    Web->>API: GET /skins/{slug} (no-store)
    alt unknown or hidden slug
        API-->>Web: 404
        Web-->>V: real HTTP 404
    else API error or outage
        API-->>Web: 5xx
        Web-->>V: error page (never a 404)
    else found
        API->>DB: item, family, cheapest from last price tick
        API-->>Web: SkinDetail
        Web-->>V: HTML with JSON-LD (Product only with a soʻm price)
    end

    V->>API: GET /skins/{slug}/listings (browser, ip_guard bucket skins-listings)
    API->>R: GET skins:listings:{slug} (90 s)
    alt fresh cache
        R-->>API: listings
    else miss, breaker closed and budget left (18/min)
        API->>WP: search-items-by-name (4 s timeout)
        alt answer
            WP-->>API: listings
            API->>R: SET fresh 90 s and stale 1 h
        else 429 or outage
            API->>R: open skins:wax:breaker 2 min
            API->>R: GET skins:listings:{slug}:stale
            Note over API: else the snapshot's cheapest_auto, degraded true
        end
    end
    API-->>V: {items, degraded}
```

## Rules behind it

- The catalogue is ours; nothing Waxpeer-branded reaches the browser. Only `auto` listings
  count.
- A hidden item disappears from every public read. The item page 404s at once; the grid can
  show it up to 60 s and the sitemap up to 1 h (`docs/runbooks/skins-catalogue.md`).
- An outage is never a 404: an API failure renders the error page.
- Redis is never required for a page to render.
