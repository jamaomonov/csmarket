# 0013. A gone offer is never replaced by another one

- **Status**: Accepted
- **Date**: 2026-10-07
- **Deciders**: @jamaomonov
- **Tags**: backend | orders | product

## Context and problem statement

Until now, a chosen offer that was gone was quietly replaced by the cheapest other offer of
the same item:

- **At checkout (R4, ADR-0007).** The replacement was any offer priced at most 3 % above
  the price shown (`order_substitute_ceiling`), billed at no more than that price.
- **At the buy (ADR-0007 R6, ADR-0010, ADR-0012).** The worker bought one such offer, of
  any source, once.

A CS2 skin is not a fungible item: two lots of the same name differ in float, pattern and
stickers. A buyer who picked a low float or a stickered lot would receive another one
without being asked. The owner ruled on 2026-10-07: tell the buyer the skin was bought
first and give the money back, never deliver something else.

## Decision outcome

No substitutes, in any source or step.

- **Checkout.** A chosen offer that is gone answers 409 `offer_gone` with `next_offer`, the
  cheapest offer left, or `null`. The buyer sees it and decides. The ±2 % `price_changed`
  rule is unchanged.
- **The buy.** The Waxpeer, Skinslink and LIS-SKINS paths buy the chosen offer only. A
  refusal of the offer (sold, dearer than our cap, another 4xx) refunds `sold_out` to the
  balance. The other outcomes are unchanged: low balance, a broken trade link, 403, 429,
  and a lost answer.
- **The exception: a LIS-SKINS repeat after a lost answer.** If LIS-SKINS refuses the lot
  on a repeat, the refusal may be our own first purchase. It still goes to `market/info`,
  then to the `buy_unconfirmed` attention, never to a refund (ADR-0012).
- **The buyer's text.** The order card says «Этот скин уже купили до вас — деньги вернулись
  на баланс. Выберите другой в маркете.» (`web.orders.trade.soldOut`, ru / uz / en).
- **Code removed.** `orders.substitutes` (`next_offer`, `switch_source`, `stored_offers`),
  `buy_rules.substitute` and `TradeSearch`, the `retarget` / `switch` writes, checkout's
  `usd_of`, and the `order_substitute_ceiling` setting (`CSMARKET_ORDER_SUBSTITUTE_CEILING`).
- **Code moved.** `pending_buy` moves to `orders.purchase_rows`.
- **Signatures.** The buy functions and the Skinslink and LIS-SKINS reconciles lose their
  `waxpeer` and `settings` arguments, which only served the substitute search.
- **Orders already in flight.** An order bought under a `<order id>:2` key before this
  change keeps that key. Its lookups and polls read the stored key, so nothing changes for
  it.

### Positive consequences

- The buyer gets exactly the lot they chose, or their money back with a clear reason.
- The buy path is shorter and has no cross-source hand-over.

### Negative consequences

- More orders end in `sold_out` refunds; the buyer has to choose again.
- No more silent saves when a cheaper twin of the lot was available.
