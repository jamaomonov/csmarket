# Design system — the storefront

The storefront's look is built from three layers, each with one home. ADR-0009 records why;
the spec is `docs/superpowers/specs/2026-10-04-storefront-design-system-design.md`.

| Layer      | Where                                      | What                                                                                                                                     |
| ---------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Tokens     | `packages/config-tailwind/tokens.css`      | colours, radii, fonts, shadows — the single source; Tailwind v4 turns each into utilities (`bg-surface`, `text-fg-muted`, `rounded-lg`…) |
| Components | `packages/ui`                              | generic pieces with no money, Steam or i18n inside                                                                                       |
| Showcase   | `/[locale]/dev/ui` (dev only, 404 in prod) | every token and every component in every state                                                                                           |

## Tokens

| Group   | Token                                             | Value                                         | Use                                                    |
| ------- | ------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------ |
| Surface | `bg`                                              | `#0B0D12`                                     | page                                                   |
|         | `surface`                                         | `#13161D`                                     | panels and cards, always outlined with `border-border` |
|         | `surface-2`                                       | `#1C2029`                                     | raised: menus, tiles inside a card                     |
|         | `surface-hover`                                   | `#181C24`                                     | card and row hover                                     |
|         | `border` / `border-strong`                        | `#222731` / `#2F3542`                         | outlines, dividers / hover outline, secondary button   |
| Text    | `fg`                                              | `#F2F4F7`                                     | primary; prices                                        |
|         | `fg-muted`                                        | `#A4ABB8`                                     | secondary, any surface                                 |
|         | `fg-dim`                                          | `#7F8796`                                     | tertiary, **only on `bg` / `surface`**                 |
| Accent  | `accent` (+ `-hover`, `-active`)                  | `#4BF364`                                     | the main action; the discount                          |
|         | `accent-fg`                                       | `#0B0D12`                                     | text on accent                                         |
|         | `accent-soft`                                     | `#A7F3B2`                                     | light tint                                             |
|         | `accent-subtle`                                   | `rgb(75 243 100 / 0.12)`                      | badge background                                       |
| Status  | `success` / `danger` / `warning` / `info`         | `#2FBF71` / `#FF7A7A` / `#F5B83D` / `#5DB2FF` | states — success is not the accent                     |
| Rarity  | `rarity-consumer … rarity-contraband`, `stattrak` | Steam's colours                               | legends, filters; a card's 2 px line and a faint wash  |
| Radius  | `rounded-sm/md/lg/xl`                             | 6 / 8 / 10 / 12 px                            | badge / input, chip / card, button / panel, menu       |
| Shadow  | `shadow-menu`                                     | `0 12px 30px rgb(0 0 0 / .45)`                | dropdown menus only                                    |
| Type    | `font-sans`                                       | Onest 400–700                                 | everything                                             |
|         | `font-mono`                                       | IBM Plex Mono 500                             | codes (order numbers), not prices                      |
|         | `.num`                                            | tabular numerals                              | prices and columns of numbers                          |

Type scale, as utilities (`--text-*` in `tokens.css`; never `text-[Npx]`): `text-meta` 11 · `text-label` 12 ·
`text-small` 13 · `text-body` 14 · `text-lead` 15 · `text-title` 17 · `text-h3` 20 · `text-h2` 26 (page
titles) · `text-h1` 34 (the item price). `cn` (tailwind-merge) knows the scale, so `text-small` and a
text colour do not cancel each other.

## Components (`@csmarket/ui`)

- **Button** / `buttonVariants` — `primary` (the page's main action, green; disabled turns grey),
  `secondary` (outlined surface), `ghost` (quiet), `danger`; sizes `sm` / `md` / `lg`.
- **Chip** / `chipVariants({active})` — a filter toggle; links (category chips) use the
  class helper. Active = light (`bg-fg text-bg`): green stays for the main action.
- **Badge** — `accent` (a discount), `neutral` (a code), `danger`.
- **Panel** — the outlined surface container (`div` / `section` / `aside`).
- **Input** / `inputClass`, **Select** / `selectClass` — outlined fields; focus turns the outline
  green with a soft ring.
- **Checkbox** — a real input; **CheckMark** — the box alone, for filter options that are links.
- **Switch** — an on/off setting (`role="switch"`): the whole row is the button, ≥ 44 px tall,
  the track, the label («Выкуп») and its state in words (`states={["включён", "выключен"]}`,
  optional `hint`). Settings that are on or off use it; a filter option stays a `Checkbox`.
- **Dropdown** — a menu button (WAI-ARIA menu): items are links (pass the app's router `Link`
  as `LinkComponent`) or actions, with an optional count (`meta`), separators, a loading and a
  status row, and `onOpenChange` for loading on first open. `maxHeight` caps a long list
  (it scrolls). `strategy="fixed"` takes a menu out of a scrolling row: it is placed from the
  trigger, stays on screen and opens upwards when there is more room above.
- **Accordion** — one collapsible section (filters).
- **Logo** / **LogoMark** — the brand lockup (mark + «cs**market**», leaning 14°, sized by the
  font size, 24 px by default) and the mark alone in `currentColor`. Files for everything
  outside the apps and the rules: `docs/brand/README.md`.

Domain components stay in `apps/web`: `SkinCard`, `SkinCategoryBar`, `WeaponMenu`,
`SkinFilters`, the header pieces. They compose the components above.

## Rules

1. **Green means the main action.** The primary button and the discount badge — not prices (they
   are `fg`), not the active chip, not decoration, not status (`success`). No glows, gradients
   behind panels or lifted hovers: a hover changes the outline and the surface.
2. **Muted text by surface.** `fg-dim` on `bg` / `surface` (contrast 5.4 / 5.0); on `surface-2`
   prefer `fg-muted` (7.1 — `fg-dim` there is 4.5, the bare minimum).
3. **Icons are silhouettes** — category PNGs as a CSS mask over `currentColor`
   (`SkinCategoryIcon`), lucide for UI glyphs. No emoji.
4. **One focus style** — `focus-visible:ring-2 ring-accent ring-offset-2 ring-offset-bg`.
5. **Radii:** chips and cards 8–10, panels 12, menus 10, badges 6.
6. **Surfaces are outlined.** A `bg-surface` card carries `border border-border`; a list of rows is
   one outlined box with `divide-y`, not a stack of cards. Page titles are `text-h2 font-semibold`,
   left-aligned.

Contrast (WCAG AA, ≥ 4.5) is checked, not quoted: `apps/web/src/lib/design-tokens.test.ts` pins
the values and these ratios.

## Adding a component

1. `packages/ui/src/components/<Name>/{Name.tsx,Name.test.tsx,index.ts}`; export it from
   `packages/ui/src/index.ts`.
2. Show it in every state on `/dev/ui`.
3. Add a line under «Components» here.

The admin imports the same tokens, so it shares the palette; its layout is its own.

## Admin (apps/admin)

The admin composes its pages from `apps/admin/src/components` (admin UX review, 2026-10-09):

- **Navigation** (`app/nav.ts`, the one list of pages) — Дашборд, then the groups **Очередь**
  (Обмены, Заявки на выплату, На проверке), **Деньги** (Платежи, P2P, Продажи, Сверка),
  **Люди** (Пользователи, Запрет выкупа), **Аналитика**, **Настройки** (Цены, Каталог,
  Настройки выкупа, Оплата), **Журнал**. From `lg` a top bar: a group of one is a link, the others
  are menus; a closed menu shows the sum of its counters. Below `lg` a bottom bar of four, 56 px
  plus `env(safe-area-inset-bottom)`: Обмены, Выплаты, Проверка with their counters and «Ещё» — a
  bottom sheet with every page, each group under a heading and a divider («Ещё» counts what its
  pages wait for). Counters are red numbers, never a bare dot. The page belongs to the longest
  matching path («Сверка» is not «Продажи»; an order is «Обмены»). The bar's height is
  `--bottom-nav` (0 from `lg`): a spacer keeps the page end above it, and sticky or fixed bottom
  bars (`SaveBar`, a payout's decision) sit `bottom-(--bottom-nav)`, stacked above it — the
  navigation stays reachable on every page. API keys have no page: a key is the «API-ключ» tab of
  its owner's card.
- **PageHeader** — back link, a 22 px title, chips beside it, actions on the right, a muted meta line.
- **DataTable** — padded cells (`px-3 py-2.5`), right-aligned `tabular-nums` money, a hover row,
  a 3 px red left edge for rows needing an operator, skeleton / empty / error states, a footer
  («Показать ещё»), whole-row click, and `mobileCard` — cards instead of the table on a narrow
  screen (`useNarrow`, < 768 px).
- **Status chips** — one component, `Status` (`components/Status.tsx`): `<Status of="order"
code={status} />` reads its word and tone from the one dictionary, `lib/dictionary.ts`, which
  holds every status (order, trade, payment, top-up, sale, payout, P2P, a market's own word (`market`), Waxpeer) and
  every reason (failure, attention, payout flag, reconciliation, hold, return). Tones, not filled
  bricks: `bg-<tone>/15 text-<tone>`; `progress` (warning), `info` (a hold), `success`,
  `danger`, `neutral`, `muted`; the green accent is never a status. Chips are lower-case
  («к выплате»); a tab or a heading made of the word capitalises it (`capital`). A code the
  dictionary does not know reads «другой статус» / «другая причина» with the code small beside
  it — never a bare code, never monospace. `Reason` is the same for a reason line. The same
  state has one word everywhere: an accepted trade under Steam's protection is «принят» with
  «защита до DD.MM» under it, on the order and in «Обмены». The base `StatusChip` is for chips
  that are not statuses («админ», «API», a payout's risk flag).
- **Money** — `$` before the number, two places in lists (three only for the USD wallet), digit
  groups, a typographic minus coloured `danger`.
- **Filters** — one pattern on every list. The main status is `Tabs` (underlined, never pills,
  checkboxes or a segmented control), with a counter wherever the API counts it, red when it
  counts work; the tab lives in the URL (`?status=`, `?attention=`, `?problems=1`, `?state=`), so
  old links keep working. Secondary filters are one row of `FilterSelect` («Касса: все»; on a phone
  the selects share the row) beside a `SearchBox` in the normal font with a short placeholder
  that is never cut («Продажа, карта, имя или Steam ID»). No labelled 40 px selects, no monospace
  search. Lists: «Обмены» view, «Заявки на выплату» status, «Продажи» attention, «Платежи» status,
  «Сверка» «Все / Проблемы N», «На проверке» «Открытые N / Решённые», P2P journal result.
- **Times in lists** — one format, `listTime` / `When` (`lib/format.ts`, `components/When.tsx`):
  relative inside 24 hours («5 мин назад»), then `DD.MM HH:MM` (`DD.MM.YYYY` for an earlier
  year), the full date in the tooltip. Detail pages show the absolute `formatDateTime`.
- **UserCell**, **EmptyState**.
- **Detail pages** — `DetailGrid` (2 : 1 columns, one on phones; `sideFirst` puts the side —
  a card's «Профиль» and «Риск» — first on a phone) of `Section`s with `Row`s (label 140 px,
  muted, one column on a phone so values never break mid-word); no bare `h2` blocks. An open
  attention is a `Banner` under the header. The page's actions sit in `PageHeader.actions` on a
  wide screen and in an `ActionBar` on a phone — sticky at the bottom, above the bottom bar
  (`bottom-(--bottom-nav)`), its buttons sharing the width; rare or dangerous ones behind «⋯»
  (`MoreMenu`). A phone reads banner → summary → actions → details. Technical fields (ids to
  search a market's cabinet by, a kassa reference) fold under «Подробнее» (`More`). Empty
  sections fold into one line, «Пока пусто: Заказы, Продажи» (`EmptySections`). The header
  names the thing (an order: its skin's picture, name and price; «Продажа <number>»; a payout:
  «Продавец: <name>» as a link). A payout's «Риски» shows what needs a look in red on top and
  folds the rest under «Всё в порядке: N». A rate reads «12 650,5 сум за $» (`formatRate`).
- **Links** — a link looks like one: numbers (order, sale, payout, payment) and names in the
  accent colour, underlined on hover (`TextLink`, or `LINK` on an `<a>`); a whole-row click
  never replaces the number's own link. A chip that leads somewhere carries an accent word and
  a chevron («к выплате · заявка ›»). A dashboard tile that opens a page shows a chevron and
  lights up on hover; a figure-only tile has neither.
- **Audit log** — targets by name (the API's `target_label`: a display name, a skin, a sale
  number), never a UUID or a slug; actions and payload keys in words, a diff «нет → да». Grouped
  by day («Сегодня», «Вчера», «12 октября»; `dayHeading`), each entry's time `HH:MM` under its
  day; on a phone each entry is a card (time and action, then who · target, then the data).
- **Dialogs** — `Modal` (or the same look): a sheet from the bottom on a phone, a card on desktop,
  Esc and a click outside close it unless a request runs.
- **Money confirms** — `ConfirmSheet`: a bottom sheet (`Modal`) on a phone, so a sticky action
  bar never hides it, the amount and the card large and the main answer full width; inline under
  the buttons on desktop, scrolled into view with the focus on its first field. One green button
  per step (a payout: «Беру в работу», then «Выплачено»); dangerous actions («Отклонить»,
  «Вернуть деньги на баланс») outlined red (`DANGER_OUTLINE`) on their own row; an action the
  API would refuse is hidden, not shown disabled.
- **Money fields** — `MoneyInput` / `MoneyField` (`components/MoneyInput.tsx`): `inputMode`
  numeric (decimal for dollars and percents), the digits grouped as typed («2 000 000»), the unit
  inside on the right («сум», «$», «%», «ч»), the name read as «<label>, <unit>». It hands the form
  the typed string without the group spaces, so the API gets the same digits as before; the form
  keeps its own validation. Every soʻm or dollar amount in the admin uses it.
- **Switches** — an on/off setting is the `Switch` from `@csmarket/ui` («Выкуп: включён /
  выключен», «Доверенный», «Запретить оплату кассой», a kassa's limit), never a 14 px checkbox.
- **Settings pages** — one `SaveBar` per page: pinned to the bottom across the screen, shown only
  when something changed, «Изменено: N полей», «Сбросить», «Сохранить». Turning something off
  that customers see (a kassa, the «Выкуп» switch) asks first and says what happens on the site.
- **Tabs on a phone** — the row scrolls sideways; the active tab is kept in view and a tab that
  counts work goes first («Требуют внимания» in «Обмены»).
