# Runbook — public API

Spec: `docs/superpowers/specs/2026-10-09-public-api-design.md`; ADR-0017. This file grows with
plans B and C; today it has the USD wallet.

## USD-кошелёк

Dollar balance for API clients and for users an admin chose. Amounts are integer milli-USD
(1000 = $1) in the ledger, strings with three decimals in the API.

### Switching on and off

Admin → «Пользователи» → the card → the USD block → «Включить» / «Выключить» with a reason
(audited `wallet.usd_switch`). On: the balance page shows «USD-кошелёк» and conversion works.
Off: conversion and API purchases stop; **the dollars stay** on the account and show in the card.

### A balance left after switching off

Nothing is lost or moved. Either switch it on again, or debit it by hand (the adjust form,
dollars, a negative amount, a reason) after paying the client out outside the system. There is no
dollars-to-soʻm conversion.

### Crediting a client (YuPay) by hand

Card → the adjust form → the currency toggle «USD» → amount → reason (4..500 chars) → apply.
Books D `user_wallet_usd` / C `house_adjustments_usd` (`admin_adjust_usd`), audited
`wallet.adjust_usd`, at most 100 000 $ per step, never below zero. A comma is read as the decimal
separator: type `1000`, not `1,000` (that would be one dollar).

### What was converted (`house_fx_*`)

Each conversion adds soʻm to `house_fx_uzs` (debit-normal) and milli-USD to `house_fx_usd`
(credit-normal). Sums per currency:

```sql
SELECT a.kind, a.currency,
       COALESCE(SUM(p.amount) FILTER (WHERE p.direction = 'D'), 0)  AS debit,
       COALESCE(SUM(p.amount) FILTER (WHERE p.direction = 'C'), 0) AS credit
FROM wallet_accounts a
LEFT JOIN wallet_postings p ON p.account_id = a.id
WHERE a.kind IN ('house_fx_uzs', 'house_fx_usd')
GROUP BY a.kind, a.currency;
```

`house_fx_uzs` debits = soʻm taken from customers; `house_fx_usd` credits = milli-USD issued
(divide by 1000 for dollars). The implied average rate is the first over the second ×1000. Each
transaction's metadata keeps its rate and rate snapshot. Columns match
`apps/api/src/csmarket/modules/wallet/models.py` (`direction` is D or C).
