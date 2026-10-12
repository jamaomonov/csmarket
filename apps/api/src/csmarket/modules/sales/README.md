# `sales` — users sell skins to us (Skinslink deposits)

Spec: `docs/superpowers/specs/2026-10-08-skin-sales-design.md`. Decision: ADR-0016. Flow:
`docs/architecture/sequence-diagrams/skin-sale.mmd`. Runbook: `docs/runbooks/sales.md`.

## Owns

| Table             | What                                                                        |
| ----------------- | --------------------------------------------------------------------------- |
| `sales`           | One per deposit; `id` = Skinslink's `merchant_tx_id`; the payout fixed      |
| `sale_items`      | The items at the prices the seller saw (USD from Skinslink, soʻm ours)      |
| `payout_cards`    | Saved cards, the number encrypted (`CARD_PURPOSE`), `last4` in the clear    |
| `payout_requests` | Card payouts an admin pays by hand (`waiting_hold` → `to_pay` → `paid` / …) |
| `sale_settings`   | Row 1: the admin's document (`rules.SaleSettings`)                          |
| `sale_checks`     | «Ask Skinslink about sale N», queued by the deposit webhook                 |
| `sale_blocks`     | Users an admin stopped from selling (`POST /sell` → 409 `sell_blocked`)     |

Does not own: the Skinslink HTTP client (`skinslink`), the ledger (`wallet`), the outbox
(`notifications`), the socket (`realtime`).

## Files

- `rules.py`, `pricing.py`, `settings_store.py` — the document and the pure pricing.
- `gate.py`, `clients.py`, `inventory.py` — the switches, the Skinslink client per route, the
  kept inventory snapshot and its breaker (opened by an outage or a 403; a 429 is only that
  caller's 503, so one busy seller cannot close selling for everyone).
- `service.py` — `POST /sell`; `limits.py` — what it refuses before storing (a blocked
  seller, an item already in an open sale, the USD ceilings; advisory locks held to the
  commit); `status.py` — every transition (`apply_deposit`, `check_sale`);
  `payouts.py` — a card sale's request; `checks.py` — the webhook's queue; `reconcile.py` —
  the poll and the alert gauges; `letters.py` — the three letters.
- `cards.py`, `views.py`, `schemas.py`, `routes.py`, `cards_routes.py` — the seller's API.
  `add_card` returns the user's live card with the same number instead of a second row (the
  ≤ 3 live cards decrypted and compared under the user lock), so retrying a refused card sale
  never fills the `cards_limit`.
  `views.rows_of` loads a page's items, cards, requests and the items' catalogue look
  (`exterior`, `rarity_color` from `skin_items` by market name; `null` for an unlisted item) in
  one query each. `GET /sales?status=hold` keeps only the sales in Steam's protection.
- `admin_schemas.py`, `admin_sales.py`, `admin_payouts.py`, `admin_flags.py`,
  `admin_routes.py` — «Выкуп» (`admin_flags`: attention resolve, sell blocks).

## Boundaries

Imports `skinslink.api` (the deposit client), `wallet.api` (`credit_sale`,
`credit_payout_return`), `notifications.api` (`enqueue`), `realtime.api` (`nudge_sale`),
`fx.api`, `skins.api` (`Bracket`, `bracket_margin`, `SkinItem`), `users.api`, `auth.api`,
`admin.api`. `skinslink.routes` imports `sales.api.enqueue_sale_check`; the dashboard
`sales.api.payouts_summary`; the worker `drain_sale_checks`; the scheduler `poll_sales`.

## Money rules

- The payout is fixed at creation and is what the cart showed (`expected_payout_uzs`).
- No ledger posting before `completed`; the credit is keyed by the sale; a rejected card
  payout by the request.
- A reversal never debits: `rolled_back` / `late_deposit` wait for an admin; `credit_blocked`
  (a frozen wallet) keeps the sale where it is and retries each poll.
- A `closed` or `reverted` sale has paid nothing, so one Skinslink later reports alive
  (`new` … `completed`) is reopened and paid normally (review 2026-10-11 SB-1, SB-11); a canceled
  card request is reopened with it.
- A revert after a card sale became payable never cancels its request (the admin may be paying
  it): `rolled_back`, the request stays `to_pay`; «Выплачено» or «Отменить (откат)».

## Settings

| Env                                        | Default | Meaning                                    |
| ------------------------------------------ | ------- | ------------------------------------------ |
| `CSMARKET_SALES_ENABLED`                   | `false` | The env kill switch                        |
| `CSMARKET_SALES_INVENTORY_TIMEOUT_SECONDS` | `6`     | Skinslink `inventory` on the request path  |
| `CSMARKET_SALES_DEPOSIT_TIMEOUT_SECONDS`   | `10`    | Skinslink `create-deposit` on `POST /sell` |

The admin's document (`/admin/sales/settings`): `enabled`, `margin[]`, `rate_cut_pct`,
`balance_bonus_pct`, `card_fee_pct{uzcard, humo, uzum_visa}`, `card_min_uzs`, `min_sum_usd`,
and the optional USD ceilings `max_sale_usd`, `max_user_day_usd`, `max_day_usd` (`null` or
missing = no limit; the 24 h windows count sales that did not end `closed` / `reverted`). It
ships switched off with the demo's placeholder fees (5 %): the owner sets real ones first. The
settings answer carries `warnings` (`balance_bonus_eats_margin`), never a refusal.

## Admin (`/api/v1/admin/sales`)

`admin_routes.py` mounts the payout queue, a request's page, the sales list and page, and the
settings editor; `payouts_summary` feeds the dashboard's «К выплате» tile. Paid and reject lock
the sale, then its request (the order `status.py` takes) and need a `to_pay` request (409
`payout_not_payable`); a reject credits `amount + fee` (the pre-fee `items_uzs`) to the balance,
keyed `payout_return:{id}`. The admin's reason is free text for the admin only: the seller's
letter and sale page say just that the transfer failed and the money is on the balance
(`SaleOut` has no reason field). The full card number leaves only through the keyless `POST /payouts/{id}/reveal`, audited
`sales.card.show` / `sales.card.copy` on every call; everything else shows the last four.

Flags (review 2026-10-11): `GET ?attention=open|resolved|any&reason=…` filters the list (each
page carries `attention_open`, the count of every open one); `POST /{number}/resolve` («Проверено»,
audited `sales.attention.resolve`); `POST /payouts/{id}/cancel` («Отменить (откат)», only a
`to_pay` request of a `rolled_back` sale, audited `sales.payout.cancel`); `GET /blocks`,
`GET|PUT /blocks/{user_id}` (audited `sales.user.block` / `unblock`). The dashboard's
`payouts.sales_attention` counts the open attentions.

## Process

The worker's `sales` queue drains `sale_checks`; the scheduler's `sales.poll` (first run at
380 s, every 60 s) settles `creating` / `offered` sales (an unknown one is closed
`not_created` after 10 minutes), polls `hold` ones every 30 minutes and `not_created` ones
every 5 minutes for 24 h, and sets the gauges `csmarket_sale_payouts_overdue`,
`csmarket_sale_attention_open{reason}` and `csmarket_sale_holds_overdue`. The webhook stays open
while both Skinslink credentials are set, whatever the switches.
