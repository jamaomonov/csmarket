# «Мои сделки» — the owner's personal trading desk

Status: approved by the owner 2026-10-29.

## Why

The owner buys skins from traders he meets in chats, then sells them on: to Skinslink through
our merchant account (the trader's inventory is priced by Skinslink, e.g. $1 200; he agrees to
pay the trader $1 100 and keeps the $100), or into his own Steam account to resell on other
markets when Skinslink pays too little. Today this lives in his head and in chats. He wants one
place that prices a trader's inventory, sends the Skinslink deposit offer, and keeps a journal
of every personal deal with its profit in dollars — **kept apart from the shop's numbers**.

## Goals

- Price a trader's inventory by trade link (the «Цена выкупа» call), pick the skins, record the
  agreed price, and send the Skinslink deposit offer to the trader from the same page.
- A journal of personal deals: who, what, the price paid, how it was paid, where the skins
  went, what they brought, the profit in USD.
- A stock of skins bought into the owner's own Steam account, each with its cost, sold by hand
  later with the price received.
- A summary: profit over a period, money «in transit» (with a guarantor, in a hold), stock at
  cost, and the owner's share of our Skinslink balance.

## Non-goals

- Paying the trader or the guarantor through the site. The owner transfers by card himself and
  records it.
- Any public or customer-facing surface. No letters, no notifications to the trader.
- Reading the owner's personal Steam inventory or selling on other markets via API.
- Tax or accounting reports.

## Anti-goals (would make it a failure even if it works)

- Personal deals leaking into the shop's analytics, «Выкуп» lists, «Сверка», the sales P&L or
  their alerts — or the shop's sales leaking into «Мои сделки».
- Any other admin seeing or using it.
- A trader's trade link or name in logs.

## Who and where

The admin SPA, a new section «Мои сделки», for the owner only. Access is a new role `desk`
(granted like `admin` with the `grant_admin` script, `--role desk`); every route requires
`admin` **and** `desk`, and the menu item shows only with it. (Builder's call: the role name and
the grant flag.)

## The deal

A deal is one purchase from one trader:

- **Trader**: a free-text name / handle and an optional note (where they met, chat link). The
  trade link only when the deal sends a Skinslink deposit.
- **Items**: the skins bought (market name, Skinslink price at the time when priced, asset id
  when known). Each item has a **destination**: `skinslink` (sold to Skinslink via our deposit)
  or `stock` (into the owner's Steam account). One deal may mix both.
- **Price paid**: an amount and a currency, `UZS` or `USD`. A guarantor's fee is included by
  the owner in this amount — no separate fee field.
- **Rate**: for UZS, the CBU rate on the day of payment is filled in and can be edited per deal
  to the rate the owner actually got. Profit is always in USD.
- **Payment method**: `direct` (owner pays the trader, then gets the skins — on trust) or
  `guarantor` (owner pays a guarantor; the guarantor pays the trader after the 7-day Steam
  protection and the owner's go-ahead).
- **Status**, one line, set by the owner except where Skinslink drives it:
  `agreed` → `paid` → `received` → `closed`, or `cancelled`; a guarantor deal also has
  «гаранту подтверждено» (a timestamp) after the protection ends. A Skinslink deposit's own
  state (offer sent, accepted, hold, credited, reverted, failed) is shown beside it.

### The price paid, split over items

When a deal has more than one item, its price is split over the items in proportion to each
item's Skinslink price at pricing time (an item Skinslink did not price gets an even share of
what is left — builder's call on the exact rule, written down). A stock item's cost is its
share; that is what its later sale is measured against.

## Selling to Skinslink

From the deal, «Отправить обмен» creates a Skinslink deposit for the trader's trade link and the
chosen asset ids — the same `create-deposit` call and `min_prices` floor the shop's sales use,
with our own `merchant_tx_id` for the deal. The Skinslink bot sends the trader an offer; the
deal page shows the offer, its expiry and its state. What Skinslink credits (`amount_usd`) is
the deal's Skinslink revenue.

Deposit state comes from the same webhook and poll as the shop's sales, routed by
`merchant_tx_id` to the desk (a desk id never queues a sale check, and the reverse). A
**reverted** deposit (the trader rolled the trade back within Steam's 7 days) marks the deal
loudly: the revenue drops to zero and the deal shows the loss — the owner may already have paid.

The deal page shows **«защита до …»** (the end of Steam's 7-day protection) so the owner knows
when paying a guarantor or a trusted trader is safe. Nothing blocks him from paying earlier.

## Stock and selling by hand

A `stock` item is in the owner's Steam account. Later he marks it sold: where (free text, e.g.
«Market.csgo», «Buff», a buyer's name), the amount and currency (UZS with a rate, or USD), the
date. A stock item can also be written off (lost, reverted) with a note.

## Profit

- A deal's profit = Skinslink credited (USD) + stock items' sale amounts (USD) − the price
  paid (USD). Until every item is resolved the deal shows «прибыль пока не известна» and the
  part known so far.
- The summary over a period (today / 7 / 30 days / custom, Tashkent days): profit realised in
  the period, deals and items count, money in transit (paid, skins not yet sold or credited),
  stock at cost.

## The owner's share of our Skinslink balance

Skinslink credits desk deposits to the same merchant balance the shop uses. The desk keeps its
own running figure: credited by desk deposits − what the owner marks as taken out
(«Вывел себе», an amount in USD with a note). It is a figure on the page, not a ledger entry in
the shop's wallet. **Owner ruling 2026-10-29: only a figure.** The shop may spend the whole
Skinslink balance; the dashboard and `SkinslinkBalanceLow` keep showing the whole balance and
never read desk data. (Builder's call: whether a wallet-style double entry is worth it; the owner
asked only to see it.)

## Keeping it apart from the shop

- Own tables (`desk_*`), own module. The shop's sales tables, `wallet`, `analytics`, «Сверка»,
  the sales P&L and the sales alerts never read them.
- The «Цена выкупа» page stays as it is for the shop; the desk has its own entry point that
  reuses the same pricing call.
- Metrics stay bounded; the Skinslink call metric already counts `deposit` / `deposit_status`
  — desk calls count there too (it is one merchant account).

## Constraints

- Project rules apply (AGENTS.md): money as Decimal, USD to Skinslink's 1/1000, soʻm whole;
  `Idempotency-Key` on every write; no PII in logs (trade links, trader names); docs and ADR
  in the same change; all user-facing strings in Russian only (admin is Russian-only).
- The deposit create follows ADR-0016's rules: our id as `merchant_tx_id`, a lost answer
  resolved by asking deposit status under that id, never by sending again.

## Calls made after the builder check (mine, for the owner to check)

- **The shop's switches do not apply.** «Отправить обмен» works while the shop's buy-back is
  off and ignores the sales limits and payment-risk holds — this is the owner's own tool. It
  needs only the Skinslink credentials. So the desk has its own deposit path (reusing the
  Skinslink client), not `sales.service`.
- **Statuses Skinslink sets.** The offer accepted → `received`; credited and every item
  resolved → `closed`; reverted → `reverted` (a terminal status of its own, shown red). The
  owner can still set any status by hand, with the Skinslink state always shown beside it.
- **When profit counts.** By item: an item's profit lands on the day it is resolved (Skinslink
  credit or a stock sale), using its share of the price. A later revert is a loss on the day of
  the revert, not a rewrite of the past period.
- **Items left over.** Items Skinslink would not take, or that the trader left out of the
  offer, stay in the deal unresolved; the owner sends them again, moves them to stock, or
  writes them off. The split of the price is not recomputed.

## Left to the builder

- Table and module names, the exact deal form layout, the list's filters and search.
- The split rule's details for unpriced items.
- Whether a deal can send more than one deposit (e.g. the trader accepts only half): at least
  one per deal; more if it falls out naturally.
- Mobile layout: the owner works from a phone — the deal page and the list must work at phone
  width.
