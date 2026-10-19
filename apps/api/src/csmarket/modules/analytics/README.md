# analytics

The admin «Аналитика» page: gross profit by day and period, in soʻm and USD, and where it
comes from. Spec: `docs/superpowers/specs/2026-10-19-analytics-design.md`.

**Owns:** nothing — no table, no write, no job. It reads `orders` (orders, trades, the
Skinslink / LIS-SKINS purchases through `orders.api.spent_usd_sql`), `fx` (each order's CBU
snapshot), `skins` (category, picture), `payments` (kassa fees), `users`, `public_api` (key
owners) and `sales` (`sales_pnl_between`, the buy-back).

## The numbers

- **Counted order:** `paid_at` in the window (Tashkent days), not refunded. **Earned** =
  delivered; the rest is **in flight**.
- **Revenue** = `price_uzs` / `price_usd` (the kassa fee is the buyer's, paid to the kassa).
- **Cost** = what the market charged (`orders.costing`), the agreed cost until it says; soʻm
  at the order's own `fx_snapshots.usd_uzs`, rounded — never today's rate.
- **Profit** = revenue − cost; **gross profit** adds the buy-back's (`income_uzs − cost_uzs`).
- **Refunds** count on their refund day; **new buyers** paid for the first time ever in the
  window; **previous period** = the same length right before.
- **Продано в минус** = delivered orders with a negative profit (normally none).

## Files

| File                     | What                                                                 |
| ------------------------ | -------------------------------------------------------------------- |
| `window.py`              | `Window`, `parse_window` (≤ 366 days), `month_window`, the cache TTL |
| `lines.py`               | `order_lines` — one row per counted order, every block groups it     |
| `business.py`            | totals and days (`summary`, `by_day`), refunds, new buyers, buy-back |
| `blocks.py`, `buyers.py` | markets, channels, payments, categories, top skins, fees, buyers     |
| `losses.py`              | «Продано в минус»                                                    |
| `cache.py`, `service.py` | Redis answers; assembling the three endpoints                        |
| `routes.py`              | `GET /admin/analytics/{business,calendar,losses}` — admin only       |

## Cache

`csmarket:analytics:v1:<endpoint>:<since>:<until>:<channel>`, 120 s, 3600 s once `until` is
more than 8 days ago (past Steam's protection nothing moves). No invalidation.
