# Storefront design system — design

- **Date:** 2026-10-04
- **Owner:** @jamaomonov (approved in conversation, section by section)
- **Scope:** the storefront (`apps/web`) — the design system itself, then the header and the
  catalogue page. Other storefront pages (item, order, account, balance) are later iterations;
  the admin SPA is out of scope.
- **References:** layout and palette after aim.market (`/ru/buy/csgo`); accent green and font
  after skins.com. Approved mockups: `.superpowers/brainstorm/40350-1791072859/content/`
  (`card.html` variant B, `catalog-v2.html`, `header.html`).

## 1. Goal

Replace the current amber-on-slate look with a **documented, reusable design system** — tokens,
shared components, a written guide and a live showcase — and apply it first to the header and
the catalogue. Every later page is built from the same pieces, so a second iteration is
composition, not new styling.

**Success:** the header and the catalogue match the approved mockups at 1440 and 390 px; the
tokens, components, `docs/design-system.md` and the dev showcase exist; no catalogue behaviour
changes (filters in the URL, queries, «ещё»); `make lint typecheck test` and e2e are green.

## 2. The design system

Three layers, each with one home.

### 2.1 Tokens — `packages/config-tailwind/tokens.css` (single source of truth)

| Group   | Token                                                         | Value                                    | Use                                                                  |
| ------- | ------------------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------- |
| Surface | `--color-bg`                                                  | `#0D111B`                                | page                                                                 |
|         | `--color-surface`                                             | `#1D2434`                                | panels, cards, filter bar, sidebar                                   |
|         | `--color-surface-2`                                           | `#2C3449`                                | raised: inputs, selects, open chip, dropdown menus                   |
|         | `--color-surface-hover`                                       | `#232B3E`                                | card hover                                                           |
|         | `--color-border`                                              | `#2C3449`                                | dividers, hover outline                                              |
|         | `--color-border-strong`                                       | `#3A4460`                                | menu dividers, strong outlines                                       |
| Text    | `--color-fg`                                                  | `#FFFFFF`                                | primary                                                              |
|         | `--color-fg-muted`                                            | `#AAB2C5`                                | secondary (any surface)                                              |
|         | `--color-fg-dim`                                              | `#8A93A8`                                | tertiary — **only on `bg` / `surface`** (see §2.4)                   |
| Accent  | `--color-accent`                                              | `#4BF364`                                | the one action colour and prices                                     |
|         | `--color-accent-hover`                                        | `#6CF682`                                |                                                                      |
|         | `--color-accent-active`                                       | `#3ED957`                                |                                                                      |
|         | `--color-accent-fg`                                           | `#0D111B`                                | text on accent                                                       |
|         | `--color-accent-soft`                                         | `#A7F3B2`                                | light tint (links in text, secondary accents)                        |
|         | `--color-accent-subtle`                                       | `rgb(75 243 100 / 0.12)`                 | badge / chip-on-dark background                                      |
| Status  | `--color-success` (+`-fg`)                                    | `#2FBF71`                                | «Получено», confirmations — distinct from the accent                 |
|         | `--color-danger` (+`-fg`)                                     | `#FF5C5C`                                | errors, «Выйти»                                                      |
|         | `--color-warning` (+`-fg`)                                    | `#F5B83D`                                | warnings                                                             |
|         | `--color-info` (+`-fg`)                                       | `#5DB2FF`                                | info                                                                 |
| Rarity  | `--color-rarity-consumer`                                     | `#B0C3D9`                                | Steam rarity colours, never typed as literals                        |
|         | `--color-rarity-industrial`                                   | `#5E98D9`                                |                                                                      |
|         | `--color-rarity-milspec`                                      | `#4B69FF`                                |                                                                      |
|         | `--color-rarity-restricted`                                   | `#8847FF`                                |                                                                      |
|         | `--color-rarity-classified`                                   | `#D32CE6`                                |                                                                      |
|         | `--color-rarity-covert`                                       | `#EB4B4B`                                | also Extraordinary                                                   |
|         | `--color-rarity-contraband`                                   | `#E4AE39`                                |                                                                      |
|         | `--color-stattrak`                                            | `#CF6A32`                                | the ST™ mark                                                         |
| Radius  | `--radius-sm/md/lg/xl`                                        | 6 / 8 / 10 / 12 px                       | badge / input, chip / card / panel, menu                             |
| Spacing | `--spacing`                                                   | 4 px grid (unchanged)                    |                                                                      |
| Shadow  | `--shadow-menu`                                               | `0 12px 30px rgb(0 0 0 / 0.45)`          | dropdown menus only                                                  |
| Type    | `--font-sans`                                                 | IBM Plex Sans 400 / 500 / 600 / 700      | everything                                                           |
|         | `--font-mono`                                                 | IBM Plex Mono 500                        | codes (order numbers), not prices                                    |
|         | scale                                                         | 11 / 12 / 13 / 14 / 15 / 17 / 22 / 26 px | meta / label / body-s / body / nav / panel title / logo / page title |
| Numbers | prices use `font-variant-numeric: tabular-nums` (class `num`) |                                          | columns of sums do not jitter                                        |

The API's `rarity_color` stays the source on a card (it is Steam's own value); the rarity tokens
serve legends, filters and anything we colour ourselves. Motion tokens (`--duration-*`,
`--easing-out`) are kept.

**Fonts** load through `next/font/google` (`IBM_Plex_Sans`, `IBM_Plex_Mono`, subsets `latin`,
`latin-ext`, `cyrillic`), self-hosted by Next, `display: swap`, exposed as the existing
`--app-font-sans` / `--app-font-mono` variables. Uzbek ʻ (U+02BB) and ʼ (U+02BC) are in the
`latin` subset (checked with fontTools). Inter and JetBrains Mono are removed from the storefront.

**Admin:** the admin imports the same preset, so it **inherits the new palette and accent**
(green buttons, navy surfaces) with no layout work; its own font loading is unchanged. This is
accepted as a side effect; the admin is not restyled.

### 2.2 Components — `packages/ui` (each `<Name>/{Name.tsx,Name.test.tsx,index.ts}`)

Only components needed more than once, generic (no money, no Steam, no i18n inside):

- **Button** (exists, restyled) — `primary` (green), `secondary` (surface-2), `ghost`, `danger`;
  sizes sm / md / lg; visible focus ring.
- **Chip** — a toggle/filter button: optional leading `icon` slot, `active` state
  (`aria-pressed`), optional trailing caret when it owns a menu.
- **Dropdown** — trigger + menu: open/close, `Esc`, arrow keys, `Enter`, outside click, focus
  return to the trigger, `aria-expanded` / `aria-haspopup` / `role="menu"` + `menuitem`;
  items may carry a trailing meta (a count). Used by the language switcher, the account menu and
  the category model menus.
- **Accordion** (section) — header button + panel, `aria-expanded` / `aria-controls`,
  controlled or uncontrolled open state.
- **Input**, **Select** (native `<select>` styled), **Checkbox** (styled native input; the
  green fill is the checked state), **Badge** (`accent` / `neutral` / `danger` tones),
  **Panel** (surface container with the panel radius and padding).

Domain components stay in the storefront: `SkinCard`, `SkinCategoryBar`, `SkinFilters`, the header.

### 2.3 The guide and the showcase

- **`docs/design-system.md`** — the token table above, when to use which component, and the
  rules in §2.4. AGENTS.md §4 gains a line: «A storefront UI element → compose from
  `@csmarket/ui` and the tokens; a new shared element goes to `packages/ui` and the guide».
- **`/[locale]/dev/ui`** — a dev-only page (404 in prod, like the dev routes: it renders only
  when `NODE_ENV !== "production"`), showing every token swatch and every component in every
  state, plus a real `SkinCard` row. No Storybook (that would be a new dependency and an ADR for
  what this page already does).
- **ADR-0009 «Storefront design system»** — the switch from amber to green, Plex over Inter, the
  rules below, the showcase instead of Storybook.

### 2.4 Rules

1. **Green means action or price.** Primary buttons, the active chip, prices, the discount badge.
   Not decoration, not status (status uses `success`).
2. **Muted text by surface.** `fg-dim` (`#8A93A8`) only on `bg` / `surface` (contrast 6.1 / 5.0);
   on `surface-2` use `fg-muted` (`#8A93A8` on `#2C3449` is 4.0, below AA).
3. **Icons are silhouettes** — our category PNGs as a CSS mask over `currentColor`
   (`SkinCategoryIcon`), lucide for UI glyphs. No emoji.
4. **One focus style** — a 2 px accent ring with offset on every interactive element.
5. **Radii:** chips and cards 8–10, panels 12, menus 10, badges 6.

Measured contrast (WCAG): white on `surface` 15.5; `fg-muted` on `surface-2` 5.8; accent on
`surface` 10.6; `accent-fg` on accent 12.9 — all AA or better.

## 3. Header

- **Guest:** the logo (`Logo`), nav with icons (owner, 2026-10-05): «Продать скины» (`/sell`),
  «Маркет» (`/`), «Пополнить Steam» (`/steam`), «Отзывы» (`/reviews`); language switcher
  (RU / UZ / EN), primary «Войти через Steam». Sell, Steam top-up, reviews and the referral are
  «Скоро» pages (`ComingSoon`) under their final URLs until they are built.
- **Signed in:** language switcher, balance chip («1 250 000 сум» + a green «+» to
  `/account/balance`), avatar + name with a Dropdown with icons: «Профиль» (`/account`),
  «Транзакции» (`/account/transactions`: purchases and the balance history, one tab each),
  «Реферал» (`/account/referral`), «Выйти» (danger).
- **Below 1280 px:** the nav moves into the ☰ menu (with the account items); below 768 px only
  the logo, the balance chip (amount without «сум») and ☰ remain.
- **Language switcher:** links to the same path in the other locale (next-intl navigation),
  keeping the query string; it does not change the profile's `locale`. Labels: «Русский»,
  «Oʻzbekcha», «English»; the trigger shows `RU` / `UZ` / `EN`.
- No currency switcher (soʻm only) and no «Как это работает» (no such page).

## 4. Catalogue page

Behaviour is unchanged: filters live in the URL, the same API calls, the same «ещё» paging, the
same SEO. Only presentation and composition change.

- **Title** «Скины КС2 (CS2)» centred. Below it two columns on desktop: the filters Panel on
  the left from the top; on the right a Panel with `SkinSearch` (flex) and `SkinSort`, then the
  category Panel, then the grid (owner, 2026-10-04: the layout of the reference market).
- **Category row** (`SkinCategoryBar`) — one row of Chips inside a Panel, flat until hovered,
  each with its silhouette on the left: Все, Ножи, Перчатки, Винтовки, Пистолеты, П-пулемёты,
  Тяжёлое (short chip labels, `skins.chipLabel.*`; titles keep the full names), and «Другое» —
  one Dropdown chip for agents, cases, keys, charms and music kits (it turns green and names
  the chosen one). The row fits at 1440 px and scrolls, without a scrollbar, below that. Weapon categories (knives, gloves,
  rifles, pistols, smgs, heavy) carry a caret and a Dropdown: «Все {категория}» + the models with
  their counts, fetched on first open from `GET /skins/facets?category=…` (the `weapons` facet,
  already served). Choosing a model sets `weapon=`; «Все …» clears it. The active category chip
  is green; with a model chosen the chip label shows the model. No API change.
- **Filters** (`SkinFilters`) — a Panel of Accordions: «Цена, сум» (two Inputs), «Качество»
  (Checkboxes with the wear code at the right), «Редкость» (Checkboxes with the rarity dot),
  «StatTrak™ / Souvenir», «Фаза» (when the category has phases). «Качество» and any section
  with an active value start open. On phones the same content sits in `SkinFilterDrawer`.
- **Card** (`SkinCard`, variant B) — whole card is the link; top row: wear code, ST™, «{n} шт»;
  a discount Badge «−{n}%» (accent tone) when `discount_percent > 0`; image over a radial glow
  in `rarity_color`; weapon (dim, 12) and skin (500, 13) with the phase after «·»; price in
  accent 600 14 (`num`); a line «Steam дороже на {n}%» (dim, 11) when there is a discount;
  hover → `surface-hover` + border; focus ring.
- **Grid:** 5 columns at ≥ 1280, 4 at ≥ 1024, 3 at ≥ 640, 2 below.
- **New strings** (all three locales): the language names, the account menu items, «Steam
  дороже на {n}%», «Все {category}», the ☰ label, the balance «+» label.

## 5. Testing and done

- **`packages/ui`:** Dropdown (open/close, Esc, arrows, Enter, outside click, focus return,
  aria), Accordion (toggle, aria), Chip (`aria-pressed`, caret), Checkbox, Badge, Button variants.
- **Storefront:** existing tests updated for the new markup; new — a model in the category menu
  sets / clears `weapon=`; the language switcher keeps path and query; the signed-in header shows
  the balance and the menu items; the card shows «−N%», «Steam дороже на N%» and the wear.
- **e2e:** the existing specs pass (selectors adjusted where roles or labels moved, assertions
  unchanged).
- **Visual check:** Playwright screenshots at 1440 and 390 — catalogue as a guest, catalogue with
  a model menu open, signed-in header with the menu open — compared with the mockups.
- **Done:** tokens, components, guide, showcase and ADR-0009 in; header and catalogue match the
  mockups; ru / uz / en strings; `make lint typecheck test` and e2e green.

## 6. Out of scope

The item, order, account and balance pages' layouts (they inherit the tokens now and are
recomposed in later iterations); a «Как это работает» page; a currency switcher; the admin's
layout; Storybook; a light theme.
