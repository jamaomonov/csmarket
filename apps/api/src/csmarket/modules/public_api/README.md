# public_api

The public purchase API (spec `docs/superpowers/specs/2026-10-09-public-api-design.md`).

Owns:

- `api_keys` — one live key per user (`uq_api_keys_live_user`), `sha256` of the `csm_…` token
  only, the pricing profile (`retail` / `cost`, set by an admin) and an optional IP allowlist.

Keys are revoked, never deleted (`orders.api_key_id` is RESTRICT): deleting a user with API
orders fails on the key.

Orders placed through a key carry `orders.channel = 'api'`, `api_key_id`, `client_order_id`
(unique per owner across all their keys — a reissue neither hides old orders nor frees an old
id; `uq_orders_user_client_order_id`, 0028) and `pricing_profile`; they are paid from the USD wallet
(`wallet.purchases.debit_purchase_usd`) and refunded to it. Routes, key issuing and buying
arrive in the following tasks of plan B.
