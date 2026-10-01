# skins

The CS2 catalogue and everything Waxpeer (spec §3.2). **M1 ships only the Waxpeer
client**; the catalogue, import, price sync, listings and buying arrive in M2.

- **Public interface:** `skins.api` — `WaxpeerClient`, `WaxpeerError`,
  `WaxpeerUnavailableError`. Other modules import nothing else from here.
- **`waxpeer.WaxpeerClient`** — transport only, async `httpx`, inject `client=` in tests.
  M1 has one call: `check_tradelink(url) -> str | None` (`POST /v1/check-tradelink`):
  `None` when the link works, else Waxpeer's reason text (`info` on `success: true`,
  `msg` on `success: false`). An HTTP error status raises `WaxpeerError`; no API key or a
  network failure raises `WaxpeerUnavailableError` (no traffic without a key).
- **The API key rides the query string** (`?api=…`), so a request URL is never logged —
  only method, path and status. `httpx`/`httpcore` loggers are capped at WARNING in
  `core.logging`, and exception text from `httpx` is never logged either (it carries the
  URL); log the exception type name.
- **Nothing Waxpeer-branded reaches a browser.** Callers translate results into their own
  wire shapes (e.g. `users` maps reasons to `invalid | private | trade_ban`).
- **Tests:** `apps/api/tests/contract/test_waxpeer_check_tradelink.py` (respx; never the
  real API, never a real trade-link token).
