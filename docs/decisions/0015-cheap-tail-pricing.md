# 0015. Lighter markups on the cheap tail (cost under 1 $)

- **Status**: Accepted
- **Date**: 2026-10-07
- **Deciders**: @jamaomonov
- **Tags**: backend | pricing

## Context and problem statement

On the 2026-10-07 comparison with skinsavdo.uz, the items under 1 $ came out worse than the
rest of the catalogue:

| Range           | Shared items | We are cheaper | They are cheaper | Median gap |
| --------------- | -----------: | -------------: | ---------------: | ---------: |
| Whole catalogue |            — |           63 % |                — |     −3.0 % |
| Cost under 1 $  |        8 423 |           44 % |          31–46 % |     +0.3 % |

The minimum margin is not what does it; the markups are. Stickers take +5 pp
(`category_pp`) and items with fewer than 4 lots take +3 pp (`liquidity`). Together they mark
items at 20–50 cents up by as much as 21 %, where skinsavdo charges about 15 %.

## Decision outcome

- `PricingRules.cheap_tail = {max_cost_usd: 1, sticker_pp: 2, low_liquidity_pp: 1}` in
  `DEFAULT_RULES`. When the cost is under `max_cost_usd`, `quote()` uses:
  - `sticker_pp` in place of the stickers category markup;
  - `low_liquidity_pp` in place of the last liquidity band (`min_count` 0, under 4 lots).

  Every other band and category stays as it is. `null` switches the tail off. The admin
  form edits the three numbers («Хвост: …»).

- `min_margin_usd`: 0.03 → 0.02.
- Unchanged: `price_floor_usd` 0.10 (the acquirers' 1 000 soʻm minimum), the brackets, the
  rate and its uplift, and the outlier filter.
- From 1 $ of cost up, not a single price changes. Two tests pin this: `quote()` on 20 items
  across every bracket, category and band, and a reprice of the same 20 items.
- Example: a sticker costing 0.26 $ with 2 lots was 0.26 × 1.21 → 0.32 $ and is now
  0.26 × 1.16 → 0.31 $.

**Expected on the same comparison:** we are cheaper on 63 % of the tail and they are cheaper
on 31 %. The median gap goes to −2.1 %, and the average margin per item drops from 0.052 $ to
0.045 $.

The production database has no stored pricing document, so `DEFAULT_RULES` is what prices
the catalogue. A document saved later through the admin form carries its own `cheap_tail`.

### Positive consequences

- The cheap tail can compete; nothing priced from 1 $ up moves.

### Negative consequences

- About 0.7 cents less margin per cheap item.
- Items under about 0.25 $, where the minimum margin decides the price, get 1 cent cheaper.
