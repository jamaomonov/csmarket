# Analytics (Google Analytics 4)

The storefront sends visits and funnel events to GA4, property stream `csmarket`
(measurement id `G-M6ZV9JK48X`, `apps/web/src/lib/analytics.ts`). The admin SPA sends nothing.

## When it counts

- Only on `csmarket.uz`: `gaEnabled` checks the host in the browser, so `next dev`, the e2e
  stack, previews and tests load no tag.
- The CSP of the storefront allows `www.googletagmanager.com` (script) and
  `*.google-analytics.com`, `*.analytics.google.com`, `*.googletagmanager.com` (connect) —
  `infra/caddy/Caddyfile.prod`. A blank «Realtime» report after a deploy: check the browser
  console for a CSP block first.

## Events

| Event              | When                                    | Params                                    |
| ------------------ | --------------------------------------- | ----------------------------------------- |
| `page_view` etc.   | GA4 enhanced measurement                | the page URL                              |
| `login`            | Steam sign-in completed                 | `method: steam`                           |
| `view_item`        | an item page opened                     | slug, English name, price in UZS          |
| `begin_checkout`   | «Купить» pressed                        | slug, price in UZS                        |
| `add_payment_info` | the same press, with the chosen method  | `payment_type` (`click`, `payme`, …)      |
| `purchase`         | the order page first sees an order paid | order number, price in UZS, slug and name |
| `sell`             | a sale to us created                    | sale number, payout in UZS                |

`purchase` is sent once per order per browser and only within an hour of `paid_at`, so a
reopened old order counts nothing; GA4 also drops a repeated `transaction_id`. An order paid
in a kassa but never reopened on the site is missing from GA — the admin dashboard is the
source of truth for money, GA for the funnel.

## Never

No Steam ID, user id, email, trade link or card in any event or URL (`docs/security/pii-handling.md`).
Do not set GA4 `user_id`. A new event goes through `track()` with a typed `GaEvent`.

## Setup in the GA4 console (once)

1. Admin → Data streams → `csmarket` → Enhanced measurement: on.
2. Admin → Events: mark `purchase` as a key event (it usually is by default), and `sell` too.
3. Admin → Data settings → Data retention: 14 months.
4. Admin → Property details: currency UZS, time zone Asia/Tashkent.
