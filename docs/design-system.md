# Design system — the storefront

The storefront's look is built from three layers, each with one home. ADR-0009 records why;
the spec is `docs/superpowers/specs/2026-10-04-storefront-design-system-design.md`.

| Layer      | Where                                      | What                                                                                                                                     |
| ---------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Tokens     | `packages/config-tailwind/tokens.css`      | colours, radii, fonts, shadows — the single source; Tailwind v4 turns each into utilities (`bg-surface`, `text-fg-muted`, `rounded-lg`…) |
| Components | `packages/ui`                              | generic pieces with no money, Steam or i18n inside                                                                                       |
| Showcase   | `/[locale]/dev/ui` (dev only, 404 in prod) | every token and every component in every state                                                                                           |

## Tokens

| Group   | Token                                             | Value                                         | Use                                                           |
| ------- | ------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------------- |
| Surface | `bg`                                              | `#0D111B`                                     | page                                                          |
|         | `surface`                                         | `#1D2434`                                     | panels, cards, filter bar, sidebar                            |
|         | `surface-2`                                       | `#2C3449`                                     | raised: inputs, selects, open chip, menus                     |
|         | `surface-hover`                                   | `#232B3E`                                     | card hover                                                    |
|         | `border` / `border-strong`                        | `#2C3449` / `#3A4460`                         | dividers / menu dividers                                      |
| Text    | `fg`                                              | `#FFFFFF`                                     | primary                                                       |
|         | `fg-muted`                                        | `#AAB2C5`                                     | secondary, any surface                                        |
|         | `fg-dim`                                          | `#8A93A8`                                     | tertiary, **only on `bg` / `surface`**                        |
| Accent  | `accent` (+ `-hover`, `-active`)                  | `#4BF364`                                     | action and price                                              |
|         | `accent-fg`                                       | `#0D111B`                                     | text on accent                                                |
|         | `accent-soft`                                     | `#A7F3B2`                                     | light tint                                                    |
|         | `accent-subtle`                                   | `rgb(75 243 100 / 0.12)`                      | badge background                                              |
| Status  | `success` / `danger` / `warning` / `info`         | `#2FBF71` / `#FF7A7A` / `#F5B83D` / `#5DB2FF` | states — success is not the accent                            |
| Rarity  | `rarity-consumer … rarity-contraband`, `stattrak` | Steam's colours                               | legends and filters; a card glows in the API's `rarity_color` |
| Radius  | `rounded-sm/md/lg/xl`                             | 6 / 8 / 10 / 12 px                            | badge / input, chip / card, button / panel, menu              |
| Shadow  | `shadow-menu`                                     | `0 12px 30px rgb(0 0 0 / .45)`                | dropdown menus only                                           |
| Type    | `font-sans`                                       | IBM Plex Sans 400–700                         | everything                                                    |
|         | `font-mono`                                       | IBM Plex Mono 500                             | codes (order numbers), not prices                             |
|         | `.num`                                            | tabular numerals                              | prices and columns of numbers                                 |

Type scale: 11 meta · 12 label · 13 small body · 14 body · 15 nav · 17 panel title · 22 logo · 26 page title.

## Components (`@csmarket/ui`)

- **Button** / `buttonVariants` — `primary` (the page's main action, green), `secondary`
  (raised surface), `ghost` (quiet), `danger`; sizes `sm` / `md` / `lg`.
- **Chip** / `chipVariants({active})` — a filter toggle; links (category chips) use the
  class helper. Active = green.
- **Badge** — `accent` (a discount), `neutral` (a code), `danger`.
- **Panel** — the surface container (`div` / `section` / `aside`).
- **Input** / `inputClass`, **Select** / `selectClass` — raised fields with the focus ring.
- **Checkbox** — a real input; **CheckMark** — the box alone, for filter options that are links.
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

1. **Green means action or price.** Primary buttons, the active chip, prices, the discount
   badge. Not decoration, not status (status uses `success`).
2. **Muted text by surface.** `fg-dim` only on `bg` / `surface` (contrast 6.1 / 5.0); on
   `surface-2` use `fg-muted` (`fg-dim` there is 4.0, below AA).
3. **Icons are silhouettes** — category PNGs as a CSS mask over `currentColor`
   (`SkinCategoryIcon`), lucide for UI glyphs. No emoji.
4. **One focus style** — `focus-visible:ring-2 ring-accent ring-offset-2 ring-offset-bg`.
5. **Radii:** chips and cards 8–10, panels 12, menus 10, badges 6.

Measured contrast (WCAG): `fg` on `surface` 15.5; `fg-muted` on `surface-2` 5.8; `accent` on
`surface` 10.6; `accent-fg` on `accent` 12.9; `danger` on `surface-2` 4.9; `stattrak` on
`surface` 5.2. `apps/web/src/lib/design-tokens.test.ts` pins
the values and these ratios.

## Adding a component

1. `packages/ui/src/components/<Name>/{Name.tsx,Name.test.tsx,index.ts}`; export it from
   `packages/ui/src/index.ts`.
2. Show it in every state on `/dev/ui`.
3. Add a line under «Components» here.

The admin imports the same tokens, so it shares the palette; its layout is its own.

## Admin (apps/admin)

The admin composes its pages from `apps/admin/src/components` (admin UX review, 2026-10-09):

- **Navigation** — a top bar: Дашборд · Обмены · Выкуп ▾ · Пользователи · Платежи · Настройки ▾,
  red counters of what waits for an operator (`attention`, payouts to pay); ☰ opens a sheet on
  phones. API keys have no page: a key is the «API-ключ» tab of its owner's card.
- **PageHeader** — back link, a 22 px title, chips beside it, actions on the right, a muted meta line.
- **DataTable** — padded cells (`px-3 py-2.5`), right-aligned `tabular-nums` money, a hover row,
  a 3 px red left edge for rows needing an operator, skeleton / empty / error states, a footer
  («Показать ещё»), whole-row click, and `mobileCard` — cards instead of the table on a narrow
  screen (`useNarrow`, < 768 px).
- **StatusChip** — tones, not filled bricks: `bg-<tone>/15 text-<tone>`; `progress` (warning),
  `info` (a hold), `success`, `danger`, `neutral`, `muted`. The green accent is never a status.
- **Money** — `$` before the number, two places in lists (three only for the USD wallet), digit
  groups, a typographic minus coloured `danger`.
- **Tabs** (underlined, with counters; red when they count work), **FiltersBar** / **SearchBox** /
  **FilterSelect** (one compact row), **UserCell**, **EmptyState**.
- **Detail pages** — `DetailGrid` (2 : 1 columns, one on phones) of `Section`s with `Row`s
  (label 140 px, muted); an open attention is a `Banner` at the top, actions sit under the header,
  rare or dangerous ones behind «⋯» (`MoreMenu`).
- **Dialogs** — `Modal` (or the same look): a sheet from the bottom on a phone, a card on desktop,
  Esc and a click outside close it unless a request runs.
