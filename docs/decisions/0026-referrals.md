# 0026. Referrals: attribution at account creation, rewards pulled and booked on the ledger

- **Status**: Accepted
- **Date**: 2026-10-27
- **Deciders**: owner
- **Tags**: backend | money | data

## Context and problem statement

Uzbek CS2 channels mostly refuse plain ads; a partner who earns a percentage of what its
audience buys has a reason to post about us (spec `2026-10-27-referrals-design.md`). The admin
picks the partners and their terms; a reward lands on the partner's site balance after an 8-day
hold (Steam's 7-day trade reversal). We must decide when an account becomes a partner's, how a
delivered order turns into a reward, and how the money is booked.

## Decision drivers

- An existing customer must never be "taken" by a link.
- `orders` is the money path; it should not learn about partners.
- The reward is money on a balance: it must sit on the double-entry ledger, once per order.

## Considered options

1. **Attribution:** at the first sign-in that creates the account (the `csm_ref` cookie) vs at
   any sign-in vs at the first purchase.
2. **Reward creation:** a hook in each of the four code paths that deliver an order vs an hourly
   job that pulls delivered orders of attributed buyers.
3. **Booking:** a new wallet kind with its own house account vs an admin adjustment.

## Decision outcome

**Chosen:** attribution only when this sign-in created the account, on the storefront
(`users.sign_in_by_steam` says so); an hourly pull (`referrals.rewards.accrue`, the last 14 days)
writes one `held` reward per order, `settle` credits it after the hold as kind `referral_reward`
(D `user_wallet` / C `house_referrals`, key `referral_reward:{order_id}`).

- `orders` stays unaware of `referrals`; the reward key is the order, so the job is idempotent.
- The cookie lives on the API host (`HttpOnly`, `Lax`, 30 days), like `csm_aid`; the sign-in call
  goes there and clears it.
- A `rolled_back` attention on the order's trade or purchase cancels the reward; another open
  attention, a frozen wallet or a banned partner keeps it waiting.

### Positive consequences

- No change to the delivery paths; one place decides what earns.
- The ledger shows every reward; analytics sums them as «Партнёрам».

### Negative consequences

- Up to an hour between delivery and the `held` row; the percent is read then, not at the
  delivery instant.
- A job down more than 14 days misses deliveries older than that.
- A resolved `rolled_back` cancels the reward even if the skin stayed; the admin pays by hand.

## Validation

`test_referrals_attribution.py`, `test_referrals_rewards.py` (term edges, rollbacks resolved or
not, frozen wallet, idempotent settle), `test_wallet_referral_reward.py`.
