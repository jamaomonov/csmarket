# 0027. «Мои сделки»: the owner's personal trading desk, apart from the shop

- **Status**: Accepted
- **Date**: 2026-10-29
- **Deciders**: owner
- **Tags**: backend | admin | money

## Context and problem statement

The owner buys skins from traders he meets in chats and sells them on — to Skinslink through
our merchant account (its price minus what he paid the trader is his profit) or into his own
Steam account to resell elsewhere (spec `2026-10-29-desk-design.md`). He wants a journal of
those deals with his profit in USD, **kept apart from the shop's numbers**, and the Skinslink
deposit sent from the same page.

## Decision drivers

- Nothing of the desk may leak into the shop's analytics, «Выкуп», «Сверка», the sales P&L,
  the wallet or alerts — and the reverse.
- Only the owner sees it; other admins must not.
- A deposit must follow ADR-0016's rules: our id, one call, a lost answer resolved by status.
- A period's profit must not be rewritten when a trade is reversed days later.

## Considered options

1. **Where:** the admin SPA vs a page on the storefront vs a separate site.
2. **Deposits:** reuse `sales.service` vs a desk path on the same Skinslink client.
3. **Profit:** computed from the deals' current state vs an append-only ledger of signed rows.
4. **The owner's money on Skinslink:** a figure on the page vs wallet entries vs fencing it
   off the shop's spendable balance.

## Decision outcome

**Chosen:** a module `desk` with its own tables, routes `/api/v1/admin/desk/*` behind a new
role `desk` on top of `admin` (`admin.api.require_desk`, granted with
`grant_admin --role desk`); deposits on the same `DepositClient` with `merchant_tx_id`
`desk-{id}` — the deposit webhook hands such an id to `desk.api.mark_due` and never queues a
sale check — followed by the webhook and the 60 s `desk.poll`; profit as `desk_entries`
(`credit`, `sale`, `write_off`, `revert`), each dated when it happened; the Skinslink share as a
figure only (owner ruling 2026-10-29).

- The shop's selling switches, limits and risk holds do not apply to desk deposits: only the
  Skinslink credentials are needed.
- A revert after a credit books a negative row on the revert day; the credit day stays as it
  was. A completed deposit is polled hourly for 8 days after acceptance to catch it.
- The shop may spend the whole Skinslink balance; the dashboard and `SkinslinkBalanceLow` keep
  showing all of it and never read desk data.
- The trader's trade link, name and the note are stored for the owner only and never logged.

## Consequences

- One more synchronous Skinslink call from admin routes (`POST /admin/desk/inventory`,
  `POST /admin/desk/deals/{id}/deposit`): AGENTS §11 and the latency alerts' `handler` regexes.
- A desk deposit counts in `csmarket_skinslink_calls_total` like any other (one merchant).
- `desk` is in the 95 % coverage list.

## Amendment 2026-10-30: the bot and a turned-down deposit

- `desk_deposits` keeps the bot (`bot_name`, `bot_steam_id` from Skinslink's deposit answer)
  and its Steam profile (`bot_persona`, `bot_avatar_url`), read once per bot by `desk.poll`
  through `GetPlayerSummaries` — a scheduler call, not on a request path; a new `desk` consumer
  label on `csmarket_steam_web_api_calls_total`. Migration `0045_desk_bot`.
- «Отправить обмен» reads the trader's `inventory` first (no DB held across it, 15 s) and sends
  each item at Skinslink's price now — the floors follow it; an item gone from the inventory
  stays behind (`skins_gone` when none is left). The price paid is split again over the fresh
  prices while no item of the deal is resolved (the `price_locked` rule). Owner ruling
  2026-10-30: a resend after `price_changed` must work without a new deal.
- The deal page refreshes every 5 s while a deposit is open and shows a failed one in red with
  the reason in words; the item's Skinslink image is now saved with the deal.

## Validation

Integration tests pin a lost `create-deposit` answer adopted by the poll, the webhook's routing
both ways, a revert on a later day, the soʻm rate rule and the role gate on every route.

## References

- Spec `docs/superpowers/specs/2026-10-29-desk-design.md`, plan `docs/superpowers/plans/2026-10-29-desk.md`
- ADR-0016 (Skinslink deposits), runbook `docs/runbooks/desk.md`
