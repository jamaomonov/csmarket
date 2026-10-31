# «Мои сделки» v2 — fixes, usability, the missing pieces

Status: approved by the owner 2026-10-31 («го оба», after the audit of the same day).
Builds on `2026-10-29-desk-design.md` (still binding where this one is silent) and ADR-0027.

## Why

The owner used the desk for two days and found it awkward: no skin pictures, deals with the same
trader told apart only by price, the deal page hiding what the deal is, a stock page that does
not help selling. A three-way audit (backend bugs, UI/UX, missing functions) found two summary
bugs, one double-send risk and a list of gaps. This spec fixes them in two stages; both ship.

## Stage 1 — fixes and the everyday screens

### Pictures

Skinslink's inventory carries no picture. Every desk item without `image_url` takes our catalogue's
picture by `market_hash_name` (`skin_items.image_url`, phase ignored, first match): when a deal is
created, when items are added, and in the inventory answer of `POST /admin/desk/inventory`. A data
migration fills the existing items the same way. The manual skin picked from the catalogue keeps
its picture in the form.

### Bugs (rulings in brackets)

1. A reverted deposit sets the deal `reverted` only when none of the deal's items is left
   unresolved; otherwise the deal keeps its status, the deposit card shows the revert, and the
   deal turns `reverted` (not `closed`) when its last item is resolved, if any item of it was
   reverted.
2. Statuses the owner may set by hand: `agreed`, `paid`, `received`, `cancelled`. `closed` and
   `reverted` are set by the system only (422 on a patch). `cancelled` is refused (409
   `deal_busy`) while a deposit is open or any item is resolved; a cancelled deal can be set back.
   Summary: «в пути» = the cost of items with destination `skinslink` in state `open`/`sent`, and
   «На складе» = items `stock`/`open`, both over every deal **except cancelled**; the stock list
   excludes cancelled deals too.
3. A `creating` deposit unknown to Skinslink is given up after **60 minutes** (was 10), so a
   second «Отправить обмен» cannot race a late first offer.
4. Moving an item to `skinslink` without an `asset_id` is refused (409 `no_asset`).
5. A deposit report never erases a stored `fail_reason`, and a deposit already `completed` or
   `reverted` never goes back to an earlier status.
6. `at` / `paid_at` must carry a timezone and may not be in the future (422).

### The list

`GET /admin/desk/deals` rows add: `first_item {name, image_url}` (the dearest by Skinslink price),
`skinslink_usd` (sum over the deal's items), `note`, `protected_until`, `guarantor_released_at`.
Search `q` matches the trader **or** an item name. The page shows a status filter (chips: все /
ждут оплаты (`agreed`) / в работе (`paid`,`received`) / закрыты / отменены / откат), the search kept
in the URL with a debounce, and rows: thumbnail + dearest skin name («+N»), trader · date · method,
the note if any; right: profit (or «≈ +$X» expected from Skinslink before any revenue), under it
«paid → Skinslink $Y». A guarantor deal whose protection ended and is not yet confirmed shows a
chip «можно платить гаранту».

### The deal page

A summary block under the header: paid (сум and $ at the deal's rate), Skinslink value, profit so
far / expected, the note and the trade link. «Изменить» opens a form for trader, note, trade link,
method and guarantor (stage 2 field). The send action sits in a sticky bottom bar on a phone, and
when it cannot be used the page says why (no trade link → a link to «Изменить»; an offer is open).
«Сменить статус» moves to the bottom. Copyable offer number.

### Stock

`POST /admin/desk/stock/prices` asks Skinslink `get-prices` for the stock items' names (price only,
15 s, no DB held across it — the desk carve-out, AGENTS §11) and answers `{name: price_usd}`. The
page shows per item: cost, Skinslink now, profit at that price; a header «N скинов · $cost»; a
name filter; sort by cost or age. Selling opens in a sheet (skin and cost on top, «Продал за»
first, «Где» remembers the last value on this device). Each row opens its deal.

### Summary and words

Profit is the main figure with «· N сделок»; the other tiles are named «Зачислено Skinslink»,
«В пути», «На складе (по себестоимости)», «Мои деньги на Skinslink»; on a phone they scroll
sideways. «Вывел себе…». Words: item `open`+skinslink «ждёт отправки»; deposit `new` «Skinslink
принял заявку»; deal `reverted` «трейдер откатил обмен». Loading skeletons, an error with retry on
every desk page.

### New deal

Order: Трейдер → Трейд-ссылка + «Загрузить инвентарь» → skins → Оплата → Заметка. Method is a
two-button switch. The inventory sorts by price (dearest first) and has «Выбрать все». The bottom
bar reads «Заплачено $X · Skinslink $Y · +$Z».

## Stage 2 — the missing pieces

1. **Items after creation.** `POST /admin/desk/deals/{id}/items` (one or more `ItemIn`) and
   `DELETE /admin/desk/items/{id}` (state `open` only); both refused with `price_locked` once an
   item of the deal is resolved; both re-split the price (`recost`).
2. **Part of the skins.** `POST /deals/{id}/deposit` takes an optional `item_ids`; the send sheet
   has a checkbox per skin.
3. **A manual skin's value.** The new-deal and add-item forms take «оценка, $» for a manual skin
   (`skinslink_usd`), so the price split is fair.
4. **Undo.** `POST /admin/desk/items/{id}/undo` for a `sold` or `written_off` item: its ledger row
   is deleted and the item is `open` again (audited `desk.item.undo`). A credited or reverted item
   cannot be undone.
5. **Traders.** `GET /admin/desk/traders?q=` groups deals by `lower(trader)`: deals, paid $, profit
   $, reverts, the last trade link. The new-deal form suggests a trader and fills the last trade
   link; the deal page links «все сделки с трейдером» (the list filtered by `q`).
6. **Withdrawals history** on the desk page (the existing `GET /withdrawals`).
7. **A custom period** in the summary (from / to dates; the API already takes them).
8. **Guarantor.** `desk_deals.guarantor` (text, optional), set on the deal form and shown on the
   page.

## Not now

Attachments (receipts), CSV export, Telegram reminders.

## Constraints

AGENTS.md applies: TDD, money as Decimal, `Idempotency-Key` on every write, no PII in logs (trader
names, trade links), docs (runbook `desk.md`, ADR-0027 amendment, module README, AGENTS §11 for the
stock price call) in the same change, admin copy Russian only, phone width first.
