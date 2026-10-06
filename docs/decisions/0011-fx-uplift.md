# 0011. A 1 % uplift on the CBU rate for soʻm prices

- **Status**: Accepted
- **Date**: 2026-10-07
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | data

## Context and problem statement

Soʻm prices are the dollar price times the CBU USD/UZS rate (ruling Q3, ADR-0005). A
2026-10-07 comparison against skinsavdo.uz over 21 629 shared items: at the CBU rate we are
cheaper on 68 % of them, median −3.1 %. That is more room than parity needs.

## Decision drivers

- Keep the "cheaper on most items" position (the owner's aim: parity with a fair margin).
- Revenue reconciliation in soʻm must stay exact per order.
- Dollar prices, costs and the buy path must not change.

## Considered options

1. **Uplift on the rate** — the buyer's rate is CBU × (1 + 1 %), applied when the rate is
   handed out; snapshots stay the CBU's.
2. **Raise the margins** — the pricing rules' percentages up by one point.
3. **Store an uplifted snapshot** — record CBU × 1.01 in `fx_snapshots`.

## Decision outcome

**Chosen option:** 1, at 1 %. At +1 % we are cheaper on 67 % of the shared items (median
−2.1 %), about +500 $ a month at 50 000 $ revenue; at +2 % the edge mostly goes (52 %).

- `CSMARKET_FX_UPLIFT_PCT` (Decimal, 0..10, default 0); prod sets 1 in
  `docker-compose.prod.yml` (pricing policy lives in git, and the compose value wins over
  `secrets/api.env`).
- `fx.current_usd_uzs` returns `rate = cbu_rate × (1 + uplift / 100)` to 2 places, with
  `cbu_rate` and `uplift_pct`. Every soʻm price goes through it: catalogue, item page,
  checkout, the admin previews. The page cache key already includes the rate, so prices
  turn over by themselves.
- `fx_snapshots` and the Redis copy keep the CBU rate. An order keeps `fx_snapshot_id` and
  stores `orders.fx_uplift_pct` (migration `0019`), so its rate is reproducible.
- Untouched: `sell_price_usd`, costs, the purchase caps in dollars.

### Positive consequences

- One number to tune; reversible by a deploy; each order says what it was priced at.

### Negative consequences

- The soʻm price is no longer "the CBU rate"; nothing customer-facing claims it is.

## Validation

After the deploy, a card's soʻm price = its dollar price × 11 909 (CBU 11 790.79 × 1.01),
rounded as before. The comparison is re-run monthly.

## Alternatives considered (detail)

### Option 2

Moves dollar prices too, so dollar-side comparisons and margin reports shift; more
places to change.

### Option 3

Breaks the snapshot as the CBU record and the reconciliation against it.

## References

- [ADR-0005](./0005-skins-catalogue-fx-and-indexing.md), [ADR-0007](./0007-orders-buying-trades.md)
