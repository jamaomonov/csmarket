# skins

The CS2 catalogue and everything Waxpeer (spec §3.2). **M1 ships only the Waxpeer
client**; the catalogue, import, price sync, listings and buying arrive in M2.

- **Public interface:** `skins.api` — `WaxpeerClient`, `WaxpeerError`,
  `WaxpeerUnavailableError`. Other modules import nothing else from here.
- **`waxpeer.WaxpeerClient`** — transport only, async `httpx`, inject `client=` in tests.
  M1 has one call: `check_tradelink(url) -> str | None` (`POST /v1/check-tradelink`):
  `None` when the link works, else Waxpeer's reason text (`info` on `success: true`,
  `msg` on `success: false`). An HTTP error status raises `WaxpeerError`; no API key, a
  network failure or a 200 whose body is not a JSON object raises `WaxpeerUnavailableError`
  (no traffic without a key) — an unreadable answer is an outage, never a reason.
- **The API key rides the query string** (`?api=…`), so a request URL is never logged —
  only method, path and status. `httpx`/`httpcore` loggers are capped at WARNING in
  `core.logging`, and exception text from `httpx` is never logged either (it carries the
  URL); log the exception type name.
- **Nothing Waxpeer-branded reaches a browser.** Callers translate results into their own
  wire shapes (e.g. `users` maps reasons to `invalid | private | trade_ban`).
- **Tests:** `apps/api/tests/contract/test_waxpeer_check_tradelink.py` (respx; never the
  real API, never a real trade-link token).

## Pricing (M2)

- **`pricing`** — `PricingRules` (retail brackets, expenses, liquidity bands, category and
  weapon pp, min margin, floor, UZS rounding, Steam cap) and `quote()`; `DEFAULT_RULES` is
  the owner's launch seed. Retail only: there is no merchant channel. A stored document
  with a stray `b2b` key still loads (extra keys are ignored).
- **`repricing`** — `reprice_rows` writes `sell_price_usd` / `discount_percent` for every
  active row after each price tick and each rules write. `hidden` rows are priced too, so
  unhiding is instant. `lock_pricing` serialises writers (advisory xact lock).
- **`settings`** — `load_rules` (Redis `skins:pricing`, TTL 3600 -> `skin_pricing_rules`
  row 1 -> defaults), `save_rules` (Postgres only; the caller `publish_rules` after commit),
  `enabled_categories`.
