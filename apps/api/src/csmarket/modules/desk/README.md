# `desk` — «Мои сделки», the owner's personal trading desk

Specs `docs/superpowers/specs/2026-10-29-desk-design.md` and `2026-10-31-desk-v2-design.md`,
ADR-0027 (amendments 2026-10-30, 2026-10-31).

## Files

| File           | What                                                                                  |
| -------------- | ------------------------------------------------------------------------------------- |
| `deals.py`     | Create, change, read a deal; hand-set statuses; settling (`closed` / `reverted`)      |
| `listing.py`   | The deals list (rows with the dearest skin, Skinslink value) and the traders          |
| `items.py`     | Items after creation: add, delete (both re-split the price), undo a sale or write-off |
| `stock.py`     | Sell, move, write off; the stock list and its Skinslink prices (`get-prices`)         |
| `deposits.py`  | «Отправить обмен» and the deposit followed to the end                                 |
| `inventory.py` | A trader's inventory at Skinslink, with our catalogue's pictures                      |
| `summary.py`   | The figures and the withdrawals                                                       |

## Owns

| Table              | What                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------ |
| `desk_deals`       | One purchase from one trader: trader, note, trade link, the price paid and how       |
| `desk_items`       | A skin of a deal: Skinslink or the owner's stock, its share of the price, its ending |
| `desk_deposits`    | A Skinslink deposit for a deal; `merchant_tx_id` = `desk-{id}`; the bot that sent it |
| `desk_entries`     | The profit ledger: one signed USD row per item resolved or reverted                  |
| `desk_withdrawals` | What the owner took out of our Skinslink balance for himself                         |

## Boundaries

- Imports only `skinslink.api`, `sales.api` (`min_prices`, `inventory_client`), `fx.api`,
  `admin.api` (the role gate, idempotency, the audit of `desk.item.undo`), `users.api`,
  `skins.api` (`images_by_name`, `steam_image`: our catalogue's picture for a skin Skinslink
  sends without one) and `core`.
- The scheduler's `desk_poll` hands in `auth.api.resolve_persona` (the bot's Steam name and
  avatar, once per bot, `consumer="desk"`); the module itself does not import `auth`.
- Imported only by `skinslink.routes` (the deposit webhook hands a `desk-` id to `desk.api`)
  and the scheduler's `desk_poll` job.
- **Never read by** `sales`, `wallet`, `analytics`, the dashboard, «Сверка» or any alert; it
  never writes the shop's wallet (owner ruling 2026-10-29: the Skinslink share is a figure).
- Every route needs `admin` **and** `desk` (`admin.api.require_desk`).
- Trade links, trader names, guarantors and notes are PII-ish: never logged.
