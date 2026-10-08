# public_api

The public purchase API (spec `docs/superpowers/specs/2026-10-09-public-api-design.md`).

Owns:

- `api_keys` — one live key per user (`uq_api_keys_live_user`), `sha256` of the `csm_…` token
  only, the pricing profile (`retail` / `cost`, set by an admin) and an optional IP allowlist.

Orders placed through a key carry `orders.channel = 'api'`, `api_key_id`, `client_order_id`
(unique per key) and `pricing_profile`; they are paid from the USD wallet
(`wallet.purchases.debit_purchase_usd`) and refunded to it. Routes, key issuing and buying
arrive in the following tasks of plan B.
