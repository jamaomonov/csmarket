# Admin UI/UX audit and fixes — 2026-10-22

The owner ordered all four batches below, in order («все по порядку», 2026-10-22). UI/UX only:
no new business features, no change to what the API does (an API change is allowed only where a
page needs a field it lacks — say so in the commit). Screens were taken at 1440 and 390 px of the
local dev admin. Admins work from a phone (card payouts, `docs/runbooks/sales.md`); Russian copy,
short sentences, outcome not mechanism.

Effort: S — half a day, M — 1–2 days, L — 3+ days.

## Cross-cutting

### 1. Navigation and menu groups — M

- **Now:** in the phone menu sheet, after «Запрет выкупа» there is no divider, so «Пользователи
  / Платежи / На проверке / P2P» read as part of «ВЫКУП». The top bar has 10 items; «Выкуп» is
  both a menu and a section of «Настройки»; «Журнал» sits in «Настройки». On a phone «Заявки на
  выплату» need ☰ and a search; counters show only as a red dot.
- **Proposal:** groups **Очередь** (Обмены, Заявки на выплату, На проверке), **Деньги**
  (Платежи, P2P, Продажи, Сверка), **Люди** (Пользователи, Запрет выкупа), **Аналитика**,
  **Настройки** (Цены, Каталог, Настройки выкупа, Оплата), **Журнал**; every group in the sheet
  has a heading and a divider. On a phone a bottom bar of 4: Обмены, Выплаты, Проверка (with
  counters) and «Ещё»; 56 px, `safe-area`.
- **Files:** `app/Layout.tsx`, `docs/design-system.md` (Admin → Navigation).

### 2. One filter pattern — M

- **Now:** underlined tabs («Обмены», «Пользователи», «На проверке»), green pills («Заявки на
  выплату», search above them, placeholder cut «…имя или S»), selects «Статус: все» («Продажи»,
  «Платежи»), 40 px labelled selects («Журнал»), a segmented control (P2P journal). Monospace
  placeholder in the search of «Платежи», «Продажи», P2P. `trades-phone`: tabs scroll sideways,
  «Требуют внимания» off-screen.
- **Proposal:** the main status is always `Tabs` with counters; secondary filters one row of
  `FilterSelect`; search in the normal font. On a phone the active tab scrolls into view; a tab
  counting work comes first.
- **Files:** `components/Filters.tsx`, `components/Tabs.tsx`, `features/sales/PayoutsPage.tsx`,
  `SalesPage.tsx`, `features/payments/PaymentsPage.tsx`, `features/audit/AuditPage.tsx`,
  `features/p2p/JournalTab.tsx`.

### 3. Money confirmations on a phone — S

- **Now:** after «Выплачено» / «Отклонить» on `/payouts/:id` the confirm renders below the
  action bar and off-screen; the sticky bar covers it. Three green buttons: «Беру в работу»,
  «Скопировать номер», «Выплачено». «Отклонить» and «Отменить (откат)» look neutral.
- **Proposal:** on a phone the confirm is a bottom sheet (`Modal` already can): amount and card
  large, «Да, выплачено» full width. On desktop `scrollIntoView` + focus on the comment field.
  One green button per step («Беру в работу» → «Выплачено»); «Скопировать номер» `secondary`.
  Dangerous actions `danger-outline` on their own row. Hide «Отклонить» when `rolled_back` (the
  server answers 409 anyway). The same pattern for the refund in `OrderActions`.
- **Files:** `features/sales/PayoutActions.tsx`, `PayBlock.tsx`, `features/orders/OrderActions.tsx`,
  `components/Modal.tsx`.

### 4. Detail pages on one `Section` — M

- **Now:** four section styles. The order's «Обмен» is a large h2 without a divider and stays two
  columns on a phone, breaking words («отп / равлено»). The payment page has headings without
  cards. «Каталог» and «Цены» have their own headings. «Действия» is an h2 with one button
  «Разобрано». On a phone the order price sits below Project id / Id Waxpeer.
- **Proposal:** `TradeBlock` and `PaymentDetail` built of `Section` + `Row`; actions in
  `PageHeader.actions`, on a phone a sticky bottom bar. Phone order: banner → summary → actions
  → details; technical fields folded under «Подробнее».
- **Files:** `components/Section.tsx`, `features/orders/TradeBlock.tsx`, `OrderDetail.tsx`,
  `OrderActions.tsx`, `features/payments/PaymentDetail.tsx`, `features/catalogue/StatusCard.tsx`.

### 5. Settings forms — M

- **Now:** the «Сохранить» bar is narrower than the card and covers fields and × buttons
  (`pricing-phone`, `sale-settings-phone`). «Оплата» has two «Сохранить»; the limits grid
  breaks; the kassa order differs between blocks. A kassa switches off without a confirm. Sums
  without grouping (`2000000`). Jargon: «п.п.», «slug», «Хвост», «Брекеты». Margin brackets
  repeat labels; on a phone «От» and «Маржа» stack. An empty ~50 px band above the first card;
  «Цены» logs a `<p>` inside `<p>` warning.
- **Proposal:** one full-width `SaveBar` per page, shown only when dirty, «Изменено: N полей».
  Switching a kassa or buying off asks («Payme будет скрыт на сайте»). `MoneyInput` with
  `inputMode="numeric"`, grouping and the unit on the right. Bracket rows a 3-column grid, one
  row on a phone. Kassa limits a table «Касса | Вкл | Сумма | Окно». Plain words for jargon.
- **Files:** `features/sales/SettingsParts.tsx`, `SaleSettingsPage.tsx`,
  `features/payments/FeeSettingsPage.tsx`, `ReviewLimitsBlock.tsx`, `features/pricing/*`,
  `features/p2p/SettingsTab.tsx`, `components/PageHeader.tsx`, new `components/SaveBar.tsx`,
  `MoneyInput.tsx`.

### 6. Codes and status names — S

- **Now:** `not_accepted` in analytics «Возвраты»; «not accepted» and «6 — не состоялся» in
  monospace in an expanded trade row; `rolled_back`, `items_repriced`, `slug:` and UUIDs as
  targets in the audit log; a rate shown as `12650.5000`; «получен» in a list vs «принят, защита
  до 15.10» in the card; chips sometimes lower-case, sometimes capitalised.
- **Proposal:** one dictionary of reasons and statuses (unknown code → «другая причина» + the
  code small); names instead of UUIDs in the log; the rate «12 650,5 сум за $»; one status chip
  component instead of five.
- **Files:** `features/*/labels.ts`, `analytics/Losses.tsx` / `Blocks.tsx`, `audit/AuditPage.tsx`,
  `sales/StatusChips.tsx`, `payments/StatusChip.tsx`, `orders/StatusChip.tsx`,
  `users/TopupStatusChip.tsx`, `components/StatusChip.tsx`.

### 7. Tap targets and phone layout — S

- **Now:** «← Назад» ~20 px, «Копировать» 11 px text; 14 px checkboxes («Только проблемы»,
  «Доверенный», «Выкуп включён» — whose title sits beside «Продажа скинов выключена»); search
  36 px. Analytics is 524 px wide on a phone (grid columns lack `min-w-0`), the left axis labels
  are cut, calendar sums overflow cells.
- **Proposal:** 44 px hit areas via padding; a `Switch` in `packages/ui` (title «Выкуп», state
  «включён / выключен»); `min-w-0` on analytics columns; compact calendar sums («3,7 млн»).
- **Files:** `components/PageHeader.tsx`, `CopyButton.tsx`, `packages/ui` (+ `/dev/ui`),
  `analytics/BusinessTab.tsx`, `charts/DayChart.tsx`, `CalendarTab.tsx`,
  `sales/ReconciliationPage.tsx`, `SaleSettingsPage.tsx`.

### 8. Links that do not look like links — S

- **Now:** dashboard tiles are clickable but look static; the order number on a payment
  underlines only on hover; the «К выплате» chip on a sale leads nowhere.
- **Proposal:** numbers and names in `accent`; link tiles with a chevron and hover; the chip
  links to `/payouts/:id`.
- **Files:** `dashboard/Tile.tsx`, `payments/PaymentDetail.tsx`, `sales/SaleDetail.tsx`,
  `components/UserCell.tsx`.

## Per page

- **Дашборд:** P2 S — on a phone the three «Сделать сейчас» tiles fill the first screen: one row
  of three compact tiles. P2 S — the per-day table on «Сегодня» is one row duplicating the
  tiles: show it for 7 / 30 days only. P3 S — «Выкуп» mixes $ and сум: one currency large, the
  other small.
- **Аналитика:** P1 S — sideways scroll on a phone (§7). P2 S — «—» under tile values: hide the
  line when there is no comparison. P2 S — «Возвраты: … not_accepted 19»: translate, do not
  repeat 19. P3 M — six «Mail» rows in «Покупатели» are indistinguishable: add the Steam ID tail
  or a link to the card.
- **Обмены:** P1 S — «Требуют внимания» off-screen on a phone. P2 S — two colour bars on the
  left (attention and rarity): rarity becomes a dot by the image. P2 S — the «Обмен» column is
  almost always «—»: move the id into the expanded row, give the width to the status. P3 S —
  codes and monospace in the expanded row.
- **Заказ:** P1 M — the «Обмен» block breaks, «Действия» stands alone (§4). P2 S — the skin
  thumbnail and price in the header. P3 S — mask the trade-link token («…token=••••»), keep
  «Копировать».
- **Заявки на выплату:** P1 S — pills → `Tabs`, fix the cut placeholder. P2 S — the waiting time
  (orange after 6 h, red after 10 h) also as a bar on the card's edge. P3 S — the totals strip is
  2×2 on a phone: one row.
- **Выплата:** P1 S — the confirm and three green buttons (§3). P1 S — the banner says «Отменить
  (откат)», the runbook «Закрыть без выплаты», and «Отклонить» shows though the server refuses
  it: one name, hide the rest. P2 S — «Риски» is 11 rows of one weight: red ones on top, the
  rest folded under «Всё в порядке: 8». P3 S — «Без имени» under the title reads as a cut:
  «Продавец: без имени» with a link.
- **Продажи и продажа:** P2 S — no skin names in the list: the first skin and «+1». P2 S —
  absolute dates here, relative in «Обмены»: one format. P2 S — title «Продажа SQWHF77Q», the
  chip leads to the payout. P3 S — empty thumbnails: check the `SkinThumb` fallback.
- **Сверка:** P2 S — the «Только проблемы» checkbox → tabs «Все / Проблемы 4». P3 S — an
  unlabelled «—» in the phone card: label «зачислено».
- **Запрет выкупа:** P3 S — bare text → `EmptyState` with a link to «Заявки на выплату».
- **Пользователи и карточка:** P1 M — on a phone 4 empty sections come before «Профиль» and
  «Риск»: fold empty ones into one line, lift «Риск» and «Профиль». P2 S — 14 px checkboxes in
  «Риск»: switches, «Сохранить» only when dirty. P2 S — «API» and «Роль» columns are almost
  always empty: a role chip on admins, an API icon by the name. P3 S — in «Изменить баланс» a
  green «Сум» competes with «Продолжить»: currency as a segmented control.
- **Платежи и платёж:** P2 S — the phone card lacks the purpose and the user: add «заказ ·
  <name>». P2 S — three filters take two rows on a phone: status into tabs. P2 S — the payment
  page has no `Section`, the order number does not look like a link.
- **На проверке:** P3 S — empty state → `EmptyState` with a link to «Настройки оплаты».
- **Настройки оплаты:** P1 M — two «Сохранить», broken grid, switching a kassa off without a
  confirm (§5). P2 S — the fee block has no heading: «Комиссия касс».
- **P2P:** P2 S — tabs touch the card; rename the «Настройки» tab «Подключение и лимиты». P2 S —
  sums without grouping (§5).
- **Цены:** P1 S — the «Сохранить» bar covers fields on a phone. P2 M — «Проверить цену» on the
  right and sticky on desktop (form 2/3, check 1/3). P2 S — jargon and the empty band from the
  nested `<p>`.
- **Каталог:** P3 S — «Состояние» as four tiles like the dashboard.
- **Журнал:** P2 M — names instead of UUIDs, translated keys, moved out of «Настройки». P3 S — a
  7800 px page on a phone: group by day.
- **Вход и 404:** no remarks.

## Batches

1. **Money and the phone (~2 days):** the bottom-sheet confirm and one green button; one name
   for a payout's cancel; «Требуют внимания» not off-screen; no sideways scroll in analytics;
   `SaveBar`, one «Сохранить» on «Оплата», confirm when a kassa goes off.
2. **Navigation and filters (~2–3 days):** menu groups and the bottom bar, one filter pattern,
   tabs instead of pills and checkboxes, one date format.
3. **Detail pages and copy (~2–3 days):** `Section` everywhere, the phone order, folded empty
   sections, the status dictionary, names in the log, links.
4. **Polish (~1–2 days):** `MoneyInput`, `Switch`, 44 px targets, jargon in «Цены», catalogue
   tiles, empty states, the log by day, the masked trade-link token.

Everything in «Per page» not named in batches 1–3 lands in batch 4.
