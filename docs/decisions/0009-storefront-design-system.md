# 0009. Storefront design system

- **Status**: Accepted
- **Date**: 2026-10-04
- **Deciders**: @jamaomonov
- **Tags**: frontend

## Context and problem statement

The storefront shipped with an amber-on-slate look in Inter, styled page by page with ad-hoc
classes and a single shared component (`Button`). The owner wants a sharper market look —
layout and palette after aim.market, the green accent and the font of skins.com — and wants it
fixed as a design system that every later page reuses.

## Decision drivers

- One source of truth for colours, type and radii; no literals in components.
- Reuse: the next pages (item, order, account) should be composition, not new styling.
- Accessibility: AA contrast, keyboard-complete menus, one focus style.
- No new dependency.

## Considered options

1. **Tokens + shared components + guide + dev showcase** — tokens in `config-tailwind`,
   generic components in `packages/ui`, `docs/design-system.md`, a dev-only `/dev/ui` page.
2. **Restyle each page in place** — fastest now, no reuse, duplicated menus.
3. **Storybook for the component catalogue** — a new dependency and its own build.

## Decision outcome

**Chosen option:** 1. Navy surfaces (`#0D111B` / `#1D2434` / `#2C3449`), one green accent
`#4BF364` for action and price, IBM Plex Sans / Mono loaded with `next/font`, and five rules
(green = action or price; muted text by surface; silhouettes, no emoji; one focus style; fixed
radii). Generic components (Button, Chip, Badge, Panel, Input, Select, Checkbox, Dropdown,
Accordion) live in `packages/ui`; domain ones stay in `apps/web`. The showcase replaces
Storybook.

### Positive consequences

- Later pages compose existing pieces; the guide and the showcase show what exists.
- Contrast and token values are pinned by a test.

### Negative consequences

- The admin imports the same tokens and turns navy-and-green without its own redesign.
- Storefront pages not yet recomposed (item, order, account) inherit the tokens before their
  layouts are reworked.

## Validation

The header and the catalogue match the approved mockups at 1440 and 390 px; the token test,
the component tests and e2e are green.
