# realtime

Live order updates for the storefront (M4b, ADR-0008).

- **What it owns:** `WS /api/v1/realtime/orders`, the in-process socket registry and the API
  process's one Postgres `LISTEN order_events` connection.
- **Protocol:** open the socket, send `{"type":"auth","token":"<access token>"}` within 5 s.
  The server sends `{"type":"order.changed","number":"…"}` and `{"type":"ping"}` (every 25 s);
  it closes with **4401** on a bad, revoked or expired token (at the latest at the token's
  expiry — reconnect with a fresh one) and **4429** past the `ws-connect` ip_guard bucket.
  Nothing secret is in the URL.
- **A nudge is not data:** the client re-reads `GET /orders/{number}`; polling stays the
  reconciler.
- **How a nudge is made:** `realtime.api.nudge(db, user_id=…, number=…)` runs
  `pg_notify('order_events', '<user_id>:<number>')` in the caller's transaction, so it is
  delivered only on commit. Called by `orders`: `mark_paid`, `_claim`, `trades.apply`
  (`trade_sent` / `delivered` / `rolled_back`), `refund_to_balance`, `expire_pending`.
- **Imports:** `auth.api` only; nothing from `orders` or `payments` (they import
  `realtime.api`).
- **Metrics:** `csmarket_ws_connections`, `csmarket_ws_nudges_total`.
- **Never logged:** the token, the user id, the notify payload.
