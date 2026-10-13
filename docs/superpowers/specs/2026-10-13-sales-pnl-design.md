# Skin-sales P&L and Skinslink reconciliation (SB-4)

Approved in conversation with the owner on 2026-10-13. Closes SB-4 of ADR-0016.

## Goal

The owner sees, for today / 7 / 30 Tashkent days, whether buying skins from users (Skinslink
deposits) makes money, and which sales Skinslink credited short or not at all. No new
Skinslink calls: every amount is already in our tables.

## Owner rulings

1. **A payout to the site balance is a cost at once**, at face value with its bonus — the
   same as a card transfer. No «liabilities on balances» line.
2. **Card payouts cost what leaves the owner's card.** The admin transfers `amount_uzs`; the
   bank charges the sender 1 % on top (99 000 sent → 99 990 debited). The fee withheld from the
   seller (`card_fee_pct`) only covers it. The bank's percent is a new sale setting
   `bank_fee_pct` (default `1`), editable on «Настройки выкупа».
3. The report is in USD; soʻm costs convert at the **CBU rate** of the sale's creation, not
   our cut sale rate (that would inflate profit).

## What counts

A sale enters the period by `credited_at` (Skinslink said `completed`) in Tashkent days.

| Sale outcome                                           | Income (USD) | Cost (soʻm)                                      |
| ------------------------------------------------------ | ------------ | ------------------------------------------------ |
| `payout_to = balance`, credited                        | `amount_usd` | `payout_uzs` (bonus included)                    |
| card request `paid`                                    | `amount_usd` | `amount_uzs + bank_fee_uzs`                      |
| card request `rejected` (credited instead)             | `amount_usd` | `items_uzs` (what the balance got)               |
| card request `waiting_hold` / `to_pay`                 | `amount_usd` | `amount_uzs` + expected bank fee, as «к выплате» |
| card request `canceled` (rolled back)                  | `0`          | `0`                                              |
| any of the above with `attention_reason = rolled_back` | `0`          | as its row above (what we paid stays a cost)     |

- `amount_usd` null on a completed sale counts `0` income and is a reconciliation problem.
- `bank_fee_uzs` is a new nullable column on `payout_requests`, written at «Выплачено» as
  `ceil(amount_uzs × bank_fee_pct / 100)`. An older `paid` row without it uses the current
  setting. An undo of «Выплачено» clears it.
- CBU rate: the newest `fx_snapshots` row at or before `sales.created_at`.

## Dashboard block «Выкуп»

Added to `GET /admin/dashboard` (`sales_pnl`), the same `days` window:

- sales counted, received from Skinslink (USD);
- paid out: to cards (with the bank fee), to balances (with the bonus), still to pay — soʻm
  and USD;
- fees: withheld from sellers vs paid to the bank (soʻm);
- profit, USD and % of received;
- by day: count, received, profit.

The admin page shows it under the purchase sales, in the same card style; nothing when the
period has no sales.

## Reconciliation tab «Сверка»

`GET /admin/sales/reconciliation?days=1|7|30&problems=1&cursor=…` and a tab on the «Выкуп»
page. A row per sale credited in the period, or with an open `rolled_back` / `late_deposit`
attention: number (link to the sale), credited at, Skinslink `trade_id`, quoted USD, credited
USD, difference, flag. Flags:

- `short` — `amount_usd < quoted_usd × 0.99`;
- `missing` — completed (`credited` / `payout`) with `amount_usd` null;
- `reverted` — `attention_reason` `rolled_back` or `late_deposit`.

Totals on top: expected, credited, difference, problem count. «Только проблемы» filters.
Newest first, 50 per page, keyset by `(credited_at, id)`.

## Out of scope

Reconciling the buy side with supplier balances; a liabilities view of balances; CSV export;
asking Skinslink again.

## Testing

Unit: the per-sale P&L arithmetic for every row of the table, the flag rules, the bank-fee
rounding. Integration: the dashboard block and the reconciliation endpoint on seeded sales
(each outcome, a rolled-back one, a missing amount, a period edge in Tashkent), the
`bank_fee_uzs` write and its clearing by undo, `bank_fee_pct` in the settings document
(default 1, bounds 0–10). Admin: the block and the tab render and filter. The `sales` module
keeps its ≥ 95 % coverage.

## Docs

`modules/sales/README.md`, `docs/runbooks/sales.md` (how to read P&L and «Сверка»),
`docs/api` via `make gen-api`, ADR-0016 «SB-4 done», `docs/tech-debt.md`.
