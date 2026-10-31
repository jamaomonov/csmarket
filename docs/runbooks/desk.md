# «Мои сделки» — the owner's personal desk

Specs `2026-10-29-desk-design.md` and `2026-10-31-desk-v2-design.md`, ADR-0027. Admin → «Мои
сделки» (visible only with the `desk` role).

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
60 minutes unknown to Skinslink it is marked failed and the skins are free to send again (an
hour, so a late first offer cannot cross a second one). Do not press «Отправить обмен» twice —
it is refused while one is open.

## A deposit Skinslink turned down

The deal page shows it in red, «Skinslink отклонил обмен: …», with the reason in words
(`price_changed`: Skinslink's price fell under the one loaded with the inventory). The skins go
back to «не отправлен». The page refreshes every 5 s while an offer is open, so the state shows
by itself.

«Отправить обмен» reads the trader's inventory first and sends each skin at Skinslink's price
now, so sending again after `price_changed` works. While nothing of the deal is sold, credited or
written off, the price you paid is split again over the fresh prices; after that the split stays.
A skin no longer in the inventory stays behind («не отправлен»); none left → «Этих скинов уже нет
в инвентаре трейдера».

## The bot

The deposit card names the Skinslink bot that sends the offer (Skinslink's `bot_name`), with its
Steam avatar and a link to its profile: the poll reads them once per bot through the Steam Web
API (`consumer="desk"` in `csmarket_steam_web_api_calls_total`). Without a Steam key only the
name shows; a failed read is retried on the next poll and never holds the deposit up.

## A revert

Red banner «Трейдер откатил обмен». Skinslink took its money back (or never paid, if the revert
came during the hold); the reverted skins' profit becomes the loss of what you paid for them,
booked on the day of the revert. «Моя доля на Skinslink» drops by the credited amount. The deal
turns «трейдер откатил обмен» only once none of its skins is left open — while a «Себе» skin
still waits to be sold, the deal keeps its status and the deposit card shows the revert; it
turns `reverted` (not `closed`) when its last skin is resolved.

## Statuses by hand

«Сменить статус» offers `agreed`, `paid`, `received`, `cancelled`; `closed` and `reverted` are
set by the system. «Отменена» is refused («deal_busy») while a skin is at Skinslink or anything
of the deal is sold, credited or written off; a cancelled deal can be set back. A closed or
reverted deal's status cannot be changed by hand — undo a sale or write-off instead. Cancelled
deals are left out of «В пути», «На складе» and the stock list.

## Skins after the deal is made

- «Добавить скин» adds skins, «Удалить» takes an open one off (the last one stays). Both split
  the price again, so both are refused («price_locked») once one skin is sold, credited or
  written off.
- «Отправить обмен» can send only some of the skins (a checkbox each).
- A skin without an asset id (added by hand) cannot be moved to Skinslink («no_asset»).
- «Отменить продажу» / «Отменить списание» puts a sold or written-off skin back to open and
  deletes its profit row (audited `desk.item.undo`); a closed deal opens again. A credited or
  reverted skin cannot be undone.
- Pictures: a skin Skinslink sends without one takes our catalogue's by market name.
- Dates («Когда заплатил», «Когда продал») carry a timezone and may not be in the future.

## Stock prices and traders

- «Склад» asks Skinslink `get-prices` for the stock's names (one call, 15 s). Skinslink down →
  «desk_unavailable»: the stock still lists, without today's prices.
- «Трейдеры» group deals by name (case ignored): deals and paid $ leave out cancelled ones,
  profit, deals with a revert, and the last trade link — filled into a new deal.

## «Моя доля на Skinslink»

Everything Skinslink credited for desk deals, less reverts, less what you marked «Вывел себе».
It is a number for you only: the shop may spend the whole Skinslink balance, and the dashboard
and the `SkinslinkBalanceLow` alert ignore it.
