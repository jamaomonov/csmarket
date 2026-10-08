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

Does not own: the Skinslink HTTP client (`skinslink`), the ledger (`wallet`), the outbox
(`notifications`), the socket (`realtime`).

## Files

- `rules.py`, `pricing.py`, `settings_store.py` — the document and the pure pricing.
- `gate.py`, `clients.py`, `inventory.py` — the switches, the Skinslink client per route, the
  kept inventory snapshot and its breaker.
- `service.py` — `POST /sell`; `status.py` — every transition (`apply_deposit`, `check_sale`);
  `payouts.py` — a card sale's request; `checks.py` — the webhook's queue; `reconcile.py` —
  the poll and the overdue count; `letters.py` — the three letters.
- `cards.py`, `views.py`, `schemas.py`, `routes.py`, `cards_routes.py` — the seller's API.
- `admin_schemas.py`, `admin_sales.py`, `admin_payouts.py`, `admin_routes.py` — «Выкуп».

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
- A reversal never debits: `rolled_back` / `late_deposit` wait for an admin; `credit_blocked` (a frozen wallet) keeps the sale in `hold` and retries each poll.

## Settings

| Env                                        | Default | Meaning                                    |
| ------------------------------------------ | ------- | ------------------------------------------ |
| `CSMARKET_SALES_ENABLED`                   | `false` | The env kill switch                        |
| `CSMARKET_SALES_INVENTORY_TIMEOUT_SECONDS` | `6`     | Skinslink `inventory` on the request path  |
| `CSMARKET_SALES_DEPOSIT_TIMEOUT_SECONDS`   | `10`    | Skinslink `create-deposit` on `POST /sell` |

The admin's document (`/admin/sales/settings`): `enabled`, `margin[]`, `rate_cut_pct`,
`balance_bonus_pct`, `card_fee_pct{uzcard, humo, uzum_visa}`, `card_min_uzs`, `min_sum_usd`.
It ships switched off with the demo's placeholder fees (5 %): the owner sets real ones first.

## Admin (`/api/v1/admin/sales`)

`admin_routes.py` mounts the payout queue, a request's page, the sales list and page, and the
settings editor; `payouts_summary` feeds the dashboard's «К выплате» tile. Paid and reject lock
the sale, then its request (the order `status.py` takes) and need a `to_pay` request (409
`payout_not_payable`); a reject credits `amount + fee` (the pre-fee `items_uzs`) to the balance,
keyed `payout_return:{id}`, and the seller sees the admin's reason in the letter and on the sale
page. The full card number leaves only through the keyless `POST /payouts/{id}/reveal`, audited
`sales.card.show` / `sales.card.copy` on every call; everything else shows the last four.

## Process

The worker's `sales` queue drains `sale_checks`; the scheduler's `sales.poll` (first run at
380 s, every 60 s) settles `creating` / `offered` sales, polls `hold` ones every 30 minutes and
sets the `csmarket_sale_payouts_overdue` gauge.
