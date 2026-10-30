# «Мои сделки» — the owner's personal desk

Spec `2026-10-29-desk-design.md`, ADR-0027. Admin → «Мои сделки» (visible only with the `desk`
role).

## Give the owner access

The account must have signed in once and be an admin:

```bash
docker compose -f docker-compose.prod.yml exec api \
  python -m csmarket.scripts.grant_admin --steam-id <17 digits> --role desk
```

`--revoke --role desk` takes it back (the `admin` role stays). The script prints only an
outcome word.

## A deal step by step

1. «Новая сделка»: trader, note, trade link → «Загрузить инвентарь» → tick the skins; each goes
   to Skinslink or «Себе». Price in сум (the CBU rate is filled in; put your real rate) or $.
   A guarantor's fee goes into the price.
2. On the deal page «Отправить обмен» — a Skinslink bot offers the trader a trade.
3. When the trader accepts, the deal shows «защита до …» (Steam's 7 days). Paying a guarantor
   or a trusted trader before that date risks a revert.
4. Skinslink's credit closes the Skinslink items; «Себе» items wait in «Склад» until you mark
   them «Продал…» (where, amount, currency).

## Rules that keep the profit honest

- Nothing is sent, sold or written off before the deal has a price («Сначала укажите, сколько
  заплатили»): each skin's profit is measured against its share of it.
- Once one skin is sold, credited or written off, the price is locked. Fix a wrong price
  before the first sale.
- When the trade was saved after a lost answer, Skinslink's status gives no dollar amount: the
  deal is credited at the skins' Skinslink prices and shows «≈». Check the real figure in the
  Skinslink cabinet.

## A deposit stuck «отправляем…»

The `create-deposit` answer was lost. The 60 s `desk.poll` asks Skinslink by `desk-{id}`; after
10 minutes unknown to Skinslink it is marked failed and the skins are free to send again. Do
not press «Отправить обмен» twice — it is refused while one is open.

## A deposit Skinslink turned down

The deal page shows it in red, «Skinslink отклонил обмен: …», with the reason in words
(`price_changed`: Skinslink's price fell under the one loaded with the inventory). The skins go
back to «не отправлен». The page refreshes every 5 s while an offer is open, so the state shows
by itself.

## The bot

The deposit card names the Skinslink bot that sends the offer (Skinslink's `bot_name`), with its
Steam avatar and a link to its profile: the poll reads them once per bot through the Steam Web
API (`consumer="desk"` in `csmarket_steam_web_api_calls_total`). Without a Steam key only the
name shows; a failed read is retried on the next poll and never holds the deposit up.

## A revert

Red banner «Трейдер откатил обмен». Skinslink took its money back (or never paid, if the revert
came during the hold); the deal's profit becomes the loss of what you paid, booked on the day of
the revert. «Моя доля на Skinslink» drops by the
credited amount.

## «Моя доля на Skinslink»

Everything Skinslink credited for desk deals, less reverts, less what you marked «Вывел себе».
It is a number for you only: the shop may spend the whole Skinslink balance, and the dashboard
and the `SkinslinkBalanceLow` alert ignore it.
