# `sales` — users sell skins to us (Skinslink deposits)

Spec: `docs/superpowers/specs/2026-10-08-skin-sales-design.md`; ADR-0016.

Owns: the sale-settings document, the sale pricing, saved payout cards, the priced inventory,
sales and their items, payout requests, the sale check queue, the poll, the sale letters and
the admin's payout and sale pages. Does not own: the Skinslink HTTP client (`skinslink`), the
ledger (`wallet`), the outbox (`notifications`), the socket (`realtime`).

## Settings

| Env                                        | Default | Meaning                                    |
| ------------------------------------------ | ------- | ------------------------------------------ |
| `CSMARKET_SALES_ENABLED`                   | `false` | The env kill switch                        |
| `CSMARKET_SALES_INVENTORY_TIMEOUT_SECONDS` | `6`     | Skinslink `inventory` on the request path  |
| `CSMARKET_SALES_DEPOSIT_TIMEOUT_SECONDS`   | `10`    | Skinslink `create-deposit` on `POST /sell` |

## Admin (`/api/v1/admin/sales`)

`admin_routes.py` mounts the payout queue, a request's page, the sales list and page, and the
settings editor; `payouts_summary` feeds the dashboard's «К выплате» tile. Paid and reject lock
the sale, then its request (the order `status.py` takes) and need a `to_pay` request (409
`payout_not_payable`); a reject credits `amount + fee` to the balance, keyed `payout_return:{id}`.
The full card number leaves only through the keyless `POST /payouts/{id}/reveal`, audited
`sales.card.show` / `sales.card.copy` on every call; everything else shows the last four.
