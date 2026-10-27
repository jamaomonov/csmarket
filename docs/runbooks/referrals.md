# Runbook — Referrals (partners)

Partners earn a percentage of what the new accounts they bring buy (spec
`2026-10-27-referrals-design.md`, ADR-0026). Money lands on the partner's site balance after
8 days; there is no card withdrawal.

## Add a partner

1. The partner signs in on the site once (the account must exist).
2. Admin → «Пользователи» → find the account → «Сделать партнёром».
3. Code (latin, digits, `-`, 3–32), percent (0.1–20), term in months or «Навсегда», a note.
   Above 2 % the form warns: on skins from $1 000 the margin may go below zero.
4. Give the partner the link `https://csmarket.uz/?ref=<code>`; it works on any page.

The code cannot change once someone came by it (old links would break).

## Change terms / switch off

«Партнёры» → the partner → edit. New percent or term counts for orders delivered from then on
(the hourly job reads it). Switched off: the link stops tying new accounts, new deliveries earn
nothing, rewards already held still credit.

## How money moves

- The job `referrals.rewards` runs hourly: it writes a `held` reward for each order delivered in
  the last 14 days by an account the partner brought (within the term), then credits those whose
  8 days are over.
- A trade rolled back (`rolled_back` attention, even resolved) cancels the reward. If the skin in
  fact stayed with the buyer, pay the partner by hand: «Коррекция баланса» with the reason.
- Another open attention on the order, a frozen partner wallet or a banned partner: the reward
  waits and is credited on the first run after it clears.
- A rollback found after the reward was credited: take it back with «Коррекция баланса».

## Risk: a partner buying through its own link

A partner can sign in a second Steam account through its own link and earn on its own buys,
then turn the balance into cash through the buy-back. Partners are hand-picked; watch for:

- a partner's detail page where one brought account makes most of the revenue;
- the buyer's admin card: the same trade link or payout card as the partner's account.

Switch the partner off and adjust the balance if it happens.
