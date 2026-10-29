# 0028. A fallback USD/UZS source and a manual rate when cbu.uz is out of reach

- **Status**: Accepted
- **Date**: 2026-10-30
- **Deciders**: owner
- **Tags**: backend | money | ops

## Context and problem statement

cbu.uz (and every .uz government and bank site we tried) stopped answering our EU VPS on
2026-10-22. The hourly refresh failed quietly for a week; on 2026-10-29 the newest snapshot
passed the 7-day rule and the storefront lost its soʻm prices, so nothing could be bought.
No alert watched the rate. The owner set today's CBU rate by hand to restore sales and asked
for a lasting fix.

## Decision drivers

- Soʻm prices must not disappear because one source is unreachable.
- The rate must stay the CBU's whenever we can get it (spec §9).
- Someone must hear about a stale rate long before the 7-day cliff.

## Considered options

1. A relay inside Uzbekistan that fetches cbu.uz for us (none we own).
2. A public source reachable from the EU, used only as a fallback.
3. Raising the 7-day rule (keeps an ever older rate).

## Decision outcome

**Chosen:** option 2 plus a manual rate and alerts. `fx.refresh` asks the CBU first; when it
fails and the newest rate is 12 h old, it records open.er-api.com's daily rate as
`source='er-api'` (within ~0.2 % of the CBU on 2026-10-29: 11 983.75 vs 12 004.02). The admin
can set the CBU rate by hand («Каталог» → «Курс вручную», `source='manual'`); the fallback
never replaces a fresh rate. `csmarket_fx_rate_age_seconds` drives `FxRateStale` (> 26 h,
warn) and `FxRateExpiring` (> 5 days, page).

- A fallback rate is a market mid-rate, not the CBU's; prices move by a fraction of a percent
  while it serves. The admin page shows the source.
- No new dependency: the same `httpx` call and plausibility band as the CBU fetch.

## References

- Runbook `docs/runbooks/fx-rate.md`; module `apps/api/src/csmarket/modules/fx`.
