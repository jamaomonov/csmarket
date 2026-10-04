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

## From the storefront design-system review (2026-10-04)

Visual polish and robustness; nothing affects orders or money.

1. **Header skeleton on phones.** `Header.tsx` shows the 160 px auth skeleton at 390 px too, and
   for a guest it resolves to nothing (sign-in lives in ☰). _Fix:_ `hidden md:block` on it.
2. **Sign-in class conflict.** `buttonVariants(…) + " hidden md:inline-flex"` keeps both
   `inline-flex` and `hidden` and relies on CSS order. _Fix:_ `cn(buttonVariants(…), "hidden md:inline-flex")`.
3. **WeaponMenu's AbortController is never aborted.** It only guards against double loads.
   _Fix:_ abort on unmount, or drop the controller.
4. **Copy.** uz `nav.profile` says «trade-havola» while the account page says «almashuv
   havolasi»; en `skins.allOf.heavy` «All heavy» → «All heavy weapons».
5. **A fixed menu never flips or clamps vertically.** On a short landscape phone a long model
   list can run below the fold. _Fix:_ clamp `top` to `innerHeight − EDGE − menuHeight`, or flip
   above the trigger.
6. **LanguageSwitcher's unit test mocks `getPathname`.** It proves the concatenation, not
   next-intl's prefixing (the e2e covers that).
