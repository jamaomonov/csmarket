# Tech debt

Known shortcomings we chose to ship with, each with its effect and the fix. Take an item into
a milestone plan (or a fix PR) and delete it here in the same change.

## From the M4b final review (2026-10-02)

None of these touches money or order state.

1. **The realtime listener cannot notice a half-open connection.**
   `realtime/listener.py` only polls `conn.is_closed()`, which asyncpg sets on a FIN/RST. A
   Postgres host that vanishes without one (VM reboot, network reset, conntrack drop) leaves
   the listener "connected": no nudges, no log, no metric until an API restart. The order page
   still reconciles by polling (8–16 s). Also, if `add_listener` raises after `connect`, the
   connection leaks. _Fix:_ every ~30 s `await asyncio.wait_for(conn.execute("SELECT 1"), 5)`
   and treat a failure as lost (or TCP keepalives); close the connection in the `except`.
2. **The email sender records an outcome it did not write.** `notifications/sender.py`
   `_finish` ignores the guarded `UPDATE`'s rowcount: when a slow attempt loses to a newer
   one the row is (correctly) untouched, but the log line and `csmarket_emails_total` still
   count it — a double `sent`, or a `failed` that could fire `EmailsFailing`. _Fix:_ record
   only when `rowcount == 1`.
3. **`realtime_enabled=false` is half a switch.** It stops the listener but still mounts
   `WS /api/v1/realtime/orders`: sockets authenticate and never get a nudge. _Fix:_ close
   new sockets (e.g. 1013) when disabled, or drop the flag.
4. **A case-only email edit re-verifies.** `users/service.update_profile` compares Python
   strings against a CITEXT column: `Foo@x.uz` → `foo@x.uz` resets `email_verified_at` and
   queues a new letter. _Fix:_ compare `.lower()`.
5. **The admin preview type omits `count_auto`.** `apps/admin/src/features/pricing/api.ts`
   `PreviewIn` lacks a field the API accepts (harmless; the mirror is incomplete). _Fix:_ add
   it.

## Sell page (2026-10-06)

1. **Resolved by ADR-0016 (2026-10-08).** `/sell` now sells for real through Skinslink
   deposits; the demo inventory and the placeholder constants are gone. Remaining gaps live in
   `docs/runbooks/sales.md` («Known gaps»).

## Skinslink buy source (ADR-0010, 2026-10-06)

1. **A bare integer `listing_id` is still accepted.** `POST /orders` reads `123` as `wx:123`
   for one release, so a tab opened before the deploy can still buy
   (`orders.schemas` validator, `skins.offers.parse_offer_id`'s digit branch). _Fix:_ after
   the next deploy, accept only `wx:` / `sl:` strings, drop the branch and its tests, and
   regenerate the API client.
2. **The admin attention queue and retry are Waxpeer-only** (refund is not: ADR-0018). The trades list, its
   `attention` view and counts read `skin_trades` (the dashboard's attention count reads
   every source since ADR-0012), so a
   Skinslink attention (`source_forbidden`, `ambiguous_trade`, `rolled_back` on
   `skinslink_purchases`) is not listed there — yet `csmarket_trades_attention` counts it, so
   `TradesNeedAttention` can fire for an order the queue does not show. The operator finds it
   by number in the admin order search («Покупка Skinslink» block) and can mark it
   «Разобрано» (that works). Admin retry refuses a Skinslink order (409); the admin refund
   asks Skinslink first and books (ADR-0018). _Fix:_ read attentions from both tables in
   `admin.orders_service` and teach retry the purchase row.

## LIS-SKINS buy source (ADR-0012, 2026-10-07)

1. **The admin trades page and its attention queue list Waxpeer trades only.** A Skinslink or
   LIS-SKINS attention (`source_forbidden`, `ambiguous_trade`, `rolled_back` on its purchase
   row) shows on the order page («Покупка Skinslink» / «Покупка LIS-SKINS»), in the
   dashboard's attention count and in the `TradesNeedAttention` alert, but not in the queue.
   Admin retry refuses a LIS-SKINS order (409); the admin refund asks LIS-SKINS
   `market/info` first and books (ADR-0018). _Fix:_ as Skinslink's item above — read every
   purchase table in `admin.orders_service`; teach retry the purchase row.
2. **The export is fetched with a browser-like `User-Agent`.** Its CDN refused httpx's own
   agent on 2026-10-07 (`lisskins/export.py`, `USER_AGENT`). If the CDN changes its rules, the
   snapshot fails and `LisskinsSnapshotStale` fires. _Fix:_ revisit if LIS-SKINS publishes an
   API for the export.
3. **The snapshot downloads ~855 MB every 5 minutes** (~250 GB a day). Watch the VPS's traffic
   and CPU. _Fix:_ a longer interval, or LIS-SKINS' WebSocket feed, if either becomes a
   problem.
4. **A refused snapshot sticks.** A snapshot whose lot count drops below half of the last
   applied one is refused, and the baseline (`lisskins_state.lots`) only moves on an applied
   one. If the market really halves, every tick refuses: prices clear after 20 minutes and
   `LisskinsSnapshotStale` fires. The reset is in `docs/runbooks/lisskins.md`. _Fix:_ accept
   the lower count after a few refusals in a row that agree within ±10 %.
5. **An open attention hides a later rollback.** If a delivered LIS-SKINS order already
   carries an unresolved `ambiguous_trade` or `audit_divergence`, a rollback does not raise
   `rolled_back` on its own (`flag` keeps the open one), and the protection poll stops once
   the status is `return`. _Fix:_ let `rolled_back` replace a milder open attention.

## Public API (ADR-0017, plans B and C, 2026-10-09)

1. **API orders count 0 soʻm in the soʻm dashboards.** An API order is paid in USD: its
   `price_uzs` is `0`, so the admin dashboard's soʻm revenue and counters leave its money out.
   The refund log and the admin audit row carry `amount_usd` for such orders. _Fix:_ a dollar
   line on the dashboard.
2. **A failed webhook delivery cannot be re-sent.** After 10 attempts a delivery is `failed` and
   stays so; the partner reads the order with `GET /public/orders/{id}`. There is no resend in
   the admin. _Fix:_ an admin «resend» that sets the row `pending` again.
3. **No `channel = api` filter on the admin orders page.** API orders are read through the API
   keys page (the card lists the latest 20) or by `client_order_id` in SQL. _Fix:_ a channel
   filter in `admin.orders_service` if the volume asks for it.
