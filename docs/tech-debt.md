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

1. **The sell page is UI only.** `/sell` shows a demo inventory in dev and «Скоро» in
   production. The fee (5 %), the balance bonus (2 %) and the card minimum (50 000 soʻm) are
   placeholders in `apps/web/src/lib/sell.ts`; with the sell API they come from it, the demo
   inventory (`sell-demo.ts`) goes, and the button starts selling. The payout card brands'
   logos are in `apps/web/public/payout/` (supplied by the owner).
