# The USD/UZS rate

Soʻm prices need a rate younger than 7 days (`CSMARKET_FX_MAX_AGE_DAYS`). ADR-0028.

## Where it comes from

1. **cbu.uz**, hourly (`fx.refresh`). It refuses our EU server since 2026-10-22.
2. **open.er-api.com**, when the CBU fails and the newest rate is 12 h old
   (`source='er-api'`, «запасной источник» in the admin). Within a fraction of a percent of
   the CBU.
3. **By hand**: admin → «Каталог» → «Курс вручную» (`source='manual'`). Take today's USD
   rate from <https://cbu.uz/ru/arkhiv-kursov-valyut/>. The fallback never overwrites it
   while it is fresh; the CBU does, once it answers.

The admin's «Каталог» → «Курс ЦБ» tile shows the rate, when it was taken and its source.

## FxRateStale (warn) — the rate is over 26 h old

Both sources fail. Check the scheduler logs:

```bash
docker compose -f docker-compose.prod.yml logs scheduler --since 3h | grep fx.
```

`fx.cbu.unreachable_fallback` then `fx.refresh.failed` means the fallback failed too. Set
the rate by hand (above) and look at why open.er-api.com fails (`curl -s
https://open.er-api.com/v6/latest/USD` on the server).

## FxRateExpiring (page) — over 5 days

Soʻm prices stop at 7 days. Set the rate by hand now, then fix the source.

## The rate looks wrong

A manual rate replaces the current one at once; set the right value again. Orders keep the
snapshot they were priced with.
