# `desk` — «Мои сделки», the owner's personal trading desk

Spec `docs/superpowers/specs/2026-10-29-desk-design.md`, ADR-0027.

## Owns

| Table              | What                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------ |
| `desk_deals`       | One purchase from one trader: trader, note, trade link, the price paid and how       |
| `desk_items`       | A skin of a deal: Skinslink or the owner's stock, its share of the price, its ending |
| `desk_deposits`    | A Skinslink deposit for a deal; `merchant_tx_id` = `desk-{id}`                       |
| `desk_entries`     | The profit ledger: one signed USD row per item resolved or reverted                  |
| `desk_withdrawals` | What the owner took out of our Skinslink balance for himself                         |

## Boundaries

- Imports only `skinslink.api`, `sales.api` (`min_prices`, `inventory_client`), `fx.api`,
  `admin.api`, `users.api` and `core`.
- Imported only by `skinslink.routes` (the deposit webhook hands a `desk-` id to `desk.api`)
  and the scheduler's `desk_poll` job.
- **Never read by** `sales`, `wallet`, `analytics`, the dashboard, «Сверка» or any alert; it
  never writes the shop's wallet (owner ruling 2026-10-29: the Skinslink share is a figure).
- Every route needs `admin` **and** `desk` (`admin.api.require_desk`).
- Trade links, trader names and notes are PII-ish: never logged.
