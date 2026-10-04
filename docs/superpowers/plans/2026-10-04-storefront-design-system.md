# Storefront Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A documented, reusable storefront design system (tokens, shared components, guide, dev showcase) applied to the header and the catalogue page, matching the approved mockups.

**Architecture:** Tokens in `packages/config-tailwind/tokens.css` (Tailwind v4 `@theme`) are the single source; generic, i18n-free components live in `packages/ui` (Chip, Badge, Panel, Input, Select, Checkbox/CheckMark, Dropdown, Accordion, restyled Button); the storefront composes them — the header gains a language switcher, a balance chip and an account menu; the catalogue keeps its URL-driven behaviour and server rendering and changes only presentation: chips with silhouettes and a lazily-loaded model menu, accordion filters, card variant B.

**Tech Stack:** Next.js 15 (App Router, RSC), next-intl 4, Tailwind v4, React 19, TanStack Query 5, Vitest + Testing Library, Playwright, `next/font/google` (IBM Plex Sans / Mono).

**Spec:** `docs/superpowers/specs/2026-10-04-storefront-design-system-design.md` (approved 2026-10-04). Mockups: `.superpowers/brainstorm/40350-1791072859/content/{card.html (variant B), catalog-v2.html, header.html}`.

## Global Constraints

- Only the storefront is restyled; the admin inherits tokens and gets **no** layout or font changes.
- Catalogue behaviour is unchanged: filters live in the URL (`skinQueryString`), the same API calls, the same «ещё» paging (`SkinGridMore`), the same SEO/metadata. Category chips and filter options stay plain links (crawlable, work without JS).
- No new dependency (AGENTS §4 requires an ADR for one); no Storybook.
- TypeScript strict; no `any`; `as` only to narrow known-shape JSON/DOM with a comment; props are explicit `interface`s; files ≤ 300 LOC.
- Every user-facing string in ru / uz / en (`packages/i18n/locales/*/web.json`); Uzbek uses ʻ (U+02BB) after o/g and ʼ (U+02BC) elsewhere; copy: «вы», short, outcome not mechanism.
- Green (`accent`) means action or price only; status uses `success`. `fg-dim` only on `bg` / `surface`; on `surface-2` use `fg-muted`.
- One focus style: `focus-visible:ring-2 ring-accent ring-offset-2 ring-offset-bg`.
- Icons: category silhouettes via `SkinCategoryIcon` (CSS mask over `currentColor`), lucide for UI glyphs; no emoji.
- Conventional Commits, scopes `packages/ui`, `packages/config-tailwind`, `web/<area>`, `docs`, `e2e`; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never push.
- Dev ports: web 3100, api 8100; touch only `csmarket-dev` containers; kill by PID only.

## Review Focus

1. **Keyboard-only and screen-reader use of the menus** (language, account, model menu): Tab reaches the trigger, Enter/Space/ArrowDown open, arrows move, Esc closes and returns focus, Tab out closes. → Task 3 `Dropdown.test.tsx` «keyboard», «escape returns focus», «tab closes».
2. **The model menu when the facets request fails or is slow** — the menu must still offer «Все …» and say it could not load, never hang a spinner or throw. → Task 8 `WeaponMenu.test.tsx` «failed load still offers the category».
3. **Language switch on a filtered catalogue URL** must keep the path and the query (`?category=rifles&sort=price`), and the default locale (ru) has no prefix. → Task 6 `LanguageSwitcher.test.tsx` «keeps path and query».
4. **A chosen model that is not in the category's facet list** (stale URL `?category=rifles&weapon=Foo`) still shows on the chip and can be cleared. → Task 8 `SkinCategoryBar.test.tsx` «unknown model stays clearable».
5. **Phone width (390 px)**: the category row scrolls instead of wrapping, the header fits (logo, balance, ☰), nothing overflows horizontally. → Task 10 e2e `design.spec.ts` «no horizontal overflow at 390».

---

## File structure

```
packages/config-tailwind/tokens.css            tokens (T1)
apps/web/src/lib/design-tokens.test.ts         token contract + contrast (T1)
apps/web/src/app/[locale]/layout.tsx           IBM Plex via next/font (T1)
apps/web/src/app/not-found.tsx                 same fonts (T1)
packages/ui/src/components/
  Button/ (restyle)  Chip/  Badge/  Panel/  Input/  Select/  Checkbox/   (T2)
  Dropdown/                                                              (T3)
  Accordion/                                                             (T4)
packages/ui/src/index.ts                       exports (T2–T4)
apps/web/src/app/[locale]/dev/ui/page.tsx      dev showcase (T5)
docs/design-system.md, docs/decisions/0009-storefront-design-system.md, AGENTS.md §4 (T5)
apps/web/src/components/Header.tsx + header/{LanguageSwitcher,AccountMenu,BalanceChip,MobileMenu}.tsx (T6)
apps/web/src/components/skins/SkinCard.tsx     variant B (T7)
apps/web/src/components/skins/{SkinCategoryBar,WeaponMenu}.tsx, lib/skins.ts fetchSkinFacets (T8)
apps/web/src/components/skins/SkinFilters.tsx, app/[locale]/page.tsx, SkinSort/SkinSearch styling (T9)
e2e/tests/design.spec.ts, screenshots, final gate (T10)
packages/i18n/locales/{ru,uz,en}/web.json      strings (T6–T9)
```

---

### Task 1: Tokens and fonts

**Files:**

- Modify: `packages/config-tailwind/tokens.css`
- Modify: `apps/web/src/app/[locale]/layout.tsx`, `apps/web/src/app/not-found.tsx`
- Test: `apps/web/src/lib/design-tokens.test.ts`

**Interfaces:**

- Produces: Tailwind colour utilities `bg|text|border-{bg,surface,surface-2,surface-hover,border,border-strong,fg,fg-muted,fg-dim,accent,accent-hover,accent-active,accent-fg,accent-soft,accent-subtle,success,danger,warning,info,rarity-*,stattrak}`, `shadow-menu`, radii `rounded-sm|md|lg|xl` = 6/8/10/12 px, fonts `font-sans` (IBM Plex Sans) / `font-mono` (IBM Plex Mono). Utility class `.num` = tabular numerals.

- [ ] **Step 1: Write the failing token contract test**

```ts
// apps/web/src/lib/design-tokens.test.ts
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(
  path.resolve(__dirname, "../../../../packages/config-tailwind/tokens.css"),
  "utf8",
);

function token(name: string): string {
  const m = new RegExp(`--${name}:\\s*([^;]+);`).exec(css);
  if (!m?.[1]) throw new Error(`token --${name} missing`);
  return m[1].trim();
}

function luminance(hex: string): number {
  const v = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => Number.parseInt(v.slice(i, i + 2), 16) / 255);
  const f = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r ?? 0) + 0.7152 * f(g ?? 0) + 0.0722 * f(b ?? 0);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

describe("design tokens", () => {
  it.each([
    ["color-bg", "#0D111B"],
    ["color-surface", "#1D2434"],
    ["color-surface-2", "#2C3449"],
    ["color-surface-hover", "#232B3E"],
    ["color-fg", "#FFFFFF"],
    ["color-fg-muted", "#AAB2C5"],
    ["color-fg-dim", "#8A93A8"],
    ["color-accent", "#4BF364"],
    ["color-accent-fg", "#0D111B"],
    ["color-accent-soft", "#A7F3B2"],
    ["color-success", "#2FBF71"],
    ["color-danger", "#FF5C5C"],
    ["color-rarity-covert", "#EB4B4B"],
    ["color-stattrak", "#CF6A32"],
    ["radius-sm", "6px"],
    ["radius-md", "8px"],
    ["radius-lg", "10px"],
    ["radius-xl", "12px"],
  ])("--%s is %s", (name, value) => {
    expect(token(name).toUpperCase()).toBe(value.toUpperCase());
  });

  it("uses IBM Plex through the app font variables", () => {
    expect(token("font-sans")).toContain("var(--app-font-sans)");
    expect(token("font-sans")).toContain("IBM Plex Sans");
  });

  it.each([
    ["color-fg", "color-surface", 4.5],
    ["color-fg-muted", "color-surface-2", 4.5],
    ["color-fg-dim", "color-surface", 4.5],
    ["color-fg-dim", "color-bg", 4.5],
    ["color-accent", "color-surface", 4.5],
    ["color-accent-fg", "color-accent", 4.5],
  ])("%s on %s meets AA", (fg, bg, min) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(min);
  });
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `pnpm --filter @csmarket/web exec vitest run src/lib/design-tokens.test.ts`
Expected: FAIL (values are oklch, `color-surface-hover` missing).

- [ ] **Step 3: Rewrite the tokens**

Replace the colour, radius, typography and shadow blocks of `packages/config-tailwind/tokens.css` (keep `--spacing`, `--duration-*`, `--easing-out`; keep the header comment, updated):

```css
/* csmarket design tokens — single source of truth (docs/design-system.md, ADR-0009).
   Tailwind v4 reads them via @theme. Dark only; navy surfaces, one green accent. */

@theme {
  /* ---------- Surfaces ---------- */
  --color-bg: #0d111b;
  --color-surface: #1d2434;
  --color-surface-2: #2c3449;
  --color-surface-hover: #232b3e;
  --color-border: #2c3449;
  --color-border-strong: #3a4460;

  /* ---------- Text ---------- */
  --color-fg: #ffffff;
  --color-fg-muted: #aab2c5;
  /* only on bg / surface — on surface-2 use fg-muted (4.0:1 there) */
  --color-fg-dim: #8a93a8;

  /* ---------- Accent: action and price only ---------- */
  --color-accent: #4bf364;
  --color-accent-hover: #6cf682;
  --color-accent-active: #3ed957;
  --color-accent-fg: #0d111b;
  --color-accent-soft: #a7f3b2;
  --color-accent-subtle: rgb(75 243 100 / 0.12);

  /* ---------- Status (success is not the accent) ---------- */
  --color-success: #2fbf71;
  --color-success-fg: #0d111b;
  --color-danger: #ff5c5c;
  --color-danger-fg: #0d111b;
  --color-warning: #f5b83d;
  --color-warning-fg: #0d111b;
  --color-info: #5db2ff;
  --color-info-fg: #0d111b;

  /* ---------- Steam rarity ---------- */
  --color-rarity-consumer: #b0c3d9;
  --color-rarity-industrial: #5e98d9;
  --color-rarity-milspec: #4b69ff;
  --color-rarity-restricted: #8847ff;
  --color-rarity-classified: #d32ce6;
  --color-rarity-covert: #eb4b4b;
  --color-rarity-contraband: #e4ae39;
  --color-stattrak: #cf6a32;

  /* ---------- Spacing / radius ---------- */
  --spacing: 0.25rem;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 10px;
  --radius-xl: 12px;
  --radius-full: 9999px;

  /* ---------- Typography ---------- */
  --font-sans: var(--app-font-sans), "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--app-font-mono), "IBM Plex Mono", ui-monospace, Menlo, monospace;

  /* ---------- Shadows / motion ---------- */
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.25);
  --shadow-md: 0 6px 16px -4px rgb(0 0 0 / 0.35);
  --shadow-menu: 0 12px 30px rgb(0 0 0 / 0.45);
  --duration-fast: 120ms;
  --duration-base: 200ms;
  --easing-out: cubic-bezier(0.16, 1, 0.3, 1);
}
```

Before editing, read the current file and keep any token not listed here that the codebase still uses (`grep -rn "radius-2xl\|color-" apps packages --include=*.tsx` for names not above); add such a token back with a navy-palette value rather than delete it. Add to `packages/config-tailwind/preset.css` inside `@layer base`:

```css
.num {
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 4: Switch the storefront fonts**

In `apps/web/src/app/[locale]/layout.tsx` and `apps/web/src/app/not-found.tsx` replace the Inter / JetBrains Mono imports and instances with:

```ts
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

const sans = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext", "cyrillic"],
  weight: ["400", "500", "600", "700"],
  variable: "--app-font-sans",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin", "cyrillic"],
  weight: ["500"],
  variable: "--app-font-mono",
  display: "swap",
});
```

(keep `className={`${sans.variable} ${mono.variable}`}` on `<html>`).

- [ ] **Step 5: Run the test and the web suite**

Run: `pnpm --filter @csmarket/web exec vitest run src/lib/design-tokens.test.ts && pnpm --filter @csmarket/web test`
Expected: PASS (existing tests do not assert colours; fix any that assert old class names by updating the expectation, not the component).

- [ ] **Step 6: Commit**

```bash
git add packages/config-tailwind apps/web/src/lib/design-tokens.test.ts apps/web/src/app
git commit -m "feat(packages/config-tailwind): navy and green design tokens, IBM Plex for the storefront"
```

---

### Task 2: Base components — Button, Chip, Badge, Panel, Input, Select, Checkbox

**Files:**

- Modify: `packages/ui/src/components/Button/Button.tsx`, `Button.test.tsx`
- Create: `packages/ui/src/components/{Chip,Badge,Panel,Input,Select,Checkbox}/{Name.tsx,Name.test.tsx,index.ts}`
- Modify: `packages/ui/src/index.ts`

**Interfaces:**

- Produces:
  - `Button`, `buttonVariants({variant: "primary"|"secondary"|"ghost"|"danger", size: "sm"|"md"|"lg"})`.
  - `chipVariants({active?: boolean})`; `Chip(props: ChipProps)` — `ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> { active?: boolean; icon?: ReactNode }`, renders `<button aria-pressed={active}>`.
  - `Badge({tone?: "accent"|"neutral"|"danger", children, className})`.
  - `Panel({as?: "div"|"section"|"aside", className, children})`.
  - `Input` (forwardRef `<input>`), `inputClass` string.
  - `Select` (forwardRef `<select>`), `selectClass` string.
  - `Checkbox` (forwardRef `<input type="checkbox">` with label children) and `CheckMark({checked: boolean})` (visual box for link-based filters).

- [ ] **Step 1: Write the failing tests**

```tsx
// packages/ui/src/components/Chip/Chip.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Chip, chipVariants } from "./Chip";

describe("Chip", () => {
  it("reports its pressed state and shows the icon before the label", () => {
    render(
      <Chip active icon={<span data-testid="ico" />}>
        Ножи
      </Chip>,
    );
    const chip = screen.getByRole("button", { name: "Ножи" });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(chip.firstElementChild).toBe(screen.getByTestId("ico"));
    expect(chip.className).toContain("bg-accent");
  });

  it("is a plain surface chip when inactive", () => {
    render(<Chip>Кейсы</Chip>);
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
    expect(chipVariants({ active: false })).toContain("bg-surface");
  });
});
```

```tsx
// packages/ui/src/components/Badge/Badge.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "./Badge";

describe("Badge", () => {
  it("uses the subtle accent tone by default", () => {
    render(<Badge>−19%</Badge>);
    expect(screen.getByText("−19%").className).toContain("bg-accent-subtle");
  });
  it("supports a neutral tone", () => {
    render(<Badge tone="neutral">MW</Badge>);
    expect(screen.getByText("MW").className).toContain("bg-surface-2");
  });
});
```

```tsx
// packages/ui/src/components/Panel/Panel.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Panel } from "./Panel";

describe("Panel", () => {
  it("renders the requested element with the panel surface", () => {
    render(<Panel as="aside">Фильтры</Panel>);
    const el = screen.getByText("Фильтры");
    expect(el.tagName).toBe("ASIDE");
    expect(el.className).toContain("bg-surface");
    expect(el.className).toContain("rounded-xl");
  });
});
```

```tsx
// packages/ui/src/components/Input/Input.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Input } from "./Input";

describe("Input", () => {
  it("is a raised field with the focus ring", () => {
    render(<Input aria-label="От" />);
    const el = screen.getByRole("textbox", { name: "От" });
    expect(el.className).toContain("bg-surface-2");
    expect(el.className).toContain("focus-visible:ring-accent");
  });
});
```

```tsx
// packages/ui/src/components/Select/Select.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Select } from "./Select";

describe("Select", () => {
  it("renders a native select with its options", () => {
    render(
      <Select aria-label="Сортировка" defaultValue="b">
        <option value="a">A</option>
        <option value="b">B</option>
      </Select>,
    );
    expect(screen.getByRole("combobox", { name: "Сортировка" })).toHaveValue("b");
  });
});
```

```tsx
// packages/ui/src/components/Checkbox/Checkbox.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CheckMark, Checkbox } from "./Checkbox";

describe("Checkbox", () => {
  it("toggles and keeps its label", () => {
    render(<Checkbox>Только StatTrak™</Checkbox>);
    const box = screen.getByRole("checkbox", { name: "Только StatTrak™" });
    fireEvent.click(box);
    expect(box).toBeChecked();
  });
  it("CheckMark shows the checked state for link-based filters", () => {
    render(<CheckMark checked />);
    expect(document.querySelector("[data-check='on']")).not.toBeNull();
  });
});
```

Add to `Button.test.tsx`:

```tsx
it("has one focus style and the four variants", () => {
  render(<Button variant="secondary">S</Button>);
  const btn = screen.getByRole("button");
  expect(btn.className).toContain("focus-visible:ring-accent");
  expect(btn.className).toContain("bg-surface-2");
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `pnpm --filter @csmarket/ui test`
Expected: FAIL — modules not found, `bg-surface-2` missing on secondary.

- [ ] **Step 3: Implement**

Button — change the `secondary` and `ghost` variants and the radius:

```ts
      variant: {
        primary: "bg-accent text-accent-fg font-semibold hover:bg-accent-hover active:bg-accent-active",
        secondary: "bg-surface-2 text-fg hover:bg-border-strong active:bg-surface-2",
        ghost: "text-fg-muted hover:bg-surface hover:text-fg active:bg-surface-2",
        danger: "bg-danger text-danger-fg font-semibold hover:opacity-90 active:opacity-100",
      },
```

and the base class `rounded-md` → `rounded-lg` (10 px).

```tsx
// packages/ui/src/components/Chip/Chip.tsx
import { cva } from "class-variance-authority";
import { type ButtonHTMLAttributes, forwardRef, type ReactNode } from "react";

import { cn } from "../../lib/cn";

/** A filter toggle: surface by default, green when active. Links reuse `chipVariants`. */
export const chipVariants = cva(
  [
    "inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-3.5 py-2 text-[13px] font-medium",
    "transition-colors duration-(--duration-fast)",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
  ],
  {
    variants: {
      active: {
        true: "bg-accent text-accent-fg font-semibold",
        false: "bg-surface text-fg-muted hover:bg-surface-2 hover:text-fg",
      },
    },
    defaultVariants: { active: false },
  },
);

export interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean;
  icon?: ReactNode;
}

export const Chip = forwardRef<HTMLButtonElement, ChipProps>(
  ({ active = false, icon, className, children, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      aria-pressed={active}
      className={cn(chipVariants({ active }), className)}
      {...props}
    >
      {icon}
      {children}
    </button>
  ),
);
Chip.displayName = "Chip";
```

```tsx
// packages/ui/src/components/Badge/Badge.tsx
import { cva } from "class-variance-authority";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

const badgeVariants = cva(
  "inline-flex items-center rounded-sm px-1.5 py-0.5 text-[11px] font-semibold",
  {
    variants: {
      tone: {
        accent: "bg-accent-subtle text-accent",
        neutral: "bg-surface-2 text-fg-muted",
        danger: "bg-danger/15 text-danger",
      },
    },
    defaultVariants: { tone: "accent" },
  },
);

interface BadgeProps {
  tone?: "accent" | "neutral" | "danger";
  className?: string;
  children: ReactNode;
}

/** A small label: a discount, a wear code, a state. */
export function Badge({ tone = "accent", className, children }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)}>{children}</span>;
}
```

```tsx
// packages/ui/src/components/Panel/Panel.tsx
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

interface PanelProps {
  as?: "div" | "section" | "aside";
  className?: string;
  children: ReactNode;
}

/** The surface container: filter sidebar, toolbar, cards of content. */
export function Panel({ as: Tag = "div", className, children }: PanelProps) {
  return <Tag className={cn("bg-surface rounded-xl p-4", className)}>{children}</Tag>;
}
```

```tsx
// packages/ui/src/components/Input/Input.tsx
import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const inputClass =
  "h-10 w-full rounded-md bg-surface-2 px-3 text-[14px] text-fg placeholder:text-fg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(inputClass, className)} {...props} />
  ),
);
Input.displayName = "Input";
```

```tsx
// packages/ui/src/components/Select/Select.tsx
import { forwardRef, type SelectHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const selectClass =
  "h-10 appearance-none rounded-md bg-surface-2 pl-3 pr-9 text-[14px] font-medium text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent bg-[url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23AAB2C5' stroke-width='2.5'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")] bg-[length:12px] bg-[right_12px_center] bg-no-repeat";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select ref={ref} className={cn(selectClass, className)} {...props} />
  ),
);
Select.displayName = "Select";
```

```tsx
// packages/ui/src/components/Checkbox/Checkbox.tsx
import { Check } from "lucide-react";
import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";

/** The visual box alone — for filter options that are links, not inputs. */
export function CheckMark({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden
      data-check={checked ? "on" : "off"}
      className={cn(
        "flex size-4 shrink-0 items-center justify-center rounded-[5px]",
        checked ? "bg-accent text-accent-fg" : "bg-surface-2",
      )}
    >
      {checked && <Check className="size-3" strokeWidth={3.5} />}
    </span>
  );
}

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  children: ReactNode;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ children, className, ...props }, ref) => (
    <label
      className={cn(
        "text-fg-muted flex cursor-pointer items-center gap-2.5 text-[14px]",
        className,
      )}
    >
      <input
        ref={ref}
        type="checkbox"
        className="bg-surface-2 checked:bg-accent focus-visible:ring-accent peer size-4 appearance-none rounded-[5px] focus-visible:outline-none focus-visible:ring-2"
        {...props}
      />
      {children}
    </label>
  ),
);
Checkbox.displayName = "Checkbox";
```

Each `index.ts` re-exports its file; `packages/ui/src/index.ts` adds:

```ts
export { Chip, chipVariants, type ChipProps } from "./components/Chip";
export { Badge } from "./components/Badge";
export { Panel } from "./components/Panel";
export { Input, inputClass } from "./components/Input";
export { Select, selectClass } from "./components/Select";
export { Checkbox, CheckMark } from "./components/Checkbox";
```

- [ ] **Step 4: Run tests, lint, typecheck**

Run: `pnpm --filter @csmarket/ui test && pnpm --filter @csmarket/ui lint && pnpm --filter @csmarket/ui typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ui
git commit -m "feat(packages/ui): chip, badge, panel, input, select and checkbox on the new tokens"
```

---

### Task 3: Dropdown

**Files:**

- Create: `packages/ui/src/components/Dropdown/{Dropdown.tsx,Dropdown.test.tsx,index.ts}`
- Modify: `packages/ui/src/index.ts`

**Interfaces:**

- Produces:

```ts
export interface DropdownItem {
  key: string;
  label: ReactNode;
  href?: string; // rendered through LinkComponent
  onSelect?: () => void; // rendered as a <button>
  meta?: ReactNode; // right-aligned (a count)
  tone?: "default" | "danger" | "accent";
  current?: boolean; // aria-current + accent text
}
export interface DropdownSeparator {
  key: string;
  separator: true;
}
export type DropdownEntry = DropdownItem | DropdownSeparator;
export interface DropdownLinkProps {
  href: string;
  className: string;
  role: "menuitem";
  tabIndex: number;
  onClick: () => void;
  children: ReactNode;
  "aria-current"?: "true";
}
export interface DropdownProps {
  label: ReactNode; // trigger content
  triggerLabel?: string; // aria-label when the trigger is icon-only
  triggerClassName?: string;
  items: DropdownEntry[];
  align?: "start" | "end";
  menuClassName?: string;
  loading?: boolean; // shows a status row instead of items
  status?: ReactNode; // e.g. a load error, shown above items
  onOpenChange?: (open: boolean) => void;
  LinkComponent?: ComponentType<DropdownLinkProps>; // default: <a>
}
export function Dropdown(props: DropdownProps): JSX.Element;
```

- [ ] **Step 1: Write the failing test**

```tsx
// packages/ui/src/components/Dropdown/Dropdown.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dropdown, type DropdownEntry } from "./Dropdown";

const items: DropdownEntry[] = [
  { key: "p", label: "Профиль", href: "/account" },
  { key: "o", label: "Мои заказы", href: "/account/orders", meta: "3" },
  { key: "s", separator: true },
  { key: "x", label: "Выйти", tone: "danger", onSelect: vi.fn() },
];

function setup(extra: Partial<Parameters<typeof Dropdown>[0]> = {}) {
  render(
    <>
      <Dropdown label="Jam" items={items} {...extra} />
      <button type="button">outside</button>
    </>,
  );
  return screen.getByRole("button", { name: "Jam" });
}

describe("Dropdown", () => {
  it("opens on click and reports it", () => {
    const trigger = setup();
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem")).toHaveLength(3);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("keyboard: ArrowDown opens on the first item, arrows move, End/Home jump", () => {
    const trigger = setup();
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const [first, second, last] = screen.getAllByRole("menuitem");
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(second);
    fireEvent.keyDown(second!, { key: "End" });
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(last!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(last);
  });

  it("escape closes and returns focus to the trigger", () => {
    const trigger = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getAllByRole("menuitem")[0]!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("tab closes the menu", () => {
    const trigger = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getAllByRole("menuitem")[0]!, { key: "Tab" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("an outside pointer press closes it", () => {
    const trigger = setup();
    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("selecting an action runs it and closes", () => {
    const onSelect = vi.fn();
    render(<Dropdown label="m" items={[{ key: "a", label: "Act", onSelect }]} />);
    fireEvent.click(screen.getByRole("button", { name: "m" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Act" }));
    expect(onSelect).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("tells the owner when it opens (lazy loading) and shows loading / status rows", () => {
    const onOpenChange = vi.fn();
    render(
      <Dropdown
        label="m"
        items={[]}
        loading
        status="Не удалось загрузить"
        onOpenChange={onOpenChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "m" }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Не удалось загрузить")).toBeInTheDocument();
  });

  it("renders links through the given LinkComponent and marks the current item", () => {
    render(
      <Dropdown
        label="lang"
        items={[{ key: "ru", label: "Русский", href: "/", current: true }]}
        LinkComponent={({ children, ...p }) => (
          <a data-custom {...p}>
            {children}
          </a>
        )}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "lang" }));
    const link = screen.getByRole("menuitem", { name: "Русский" });
    expect(link).toHaveAttribute("data-custom");
    expect(link).toHaveAttribute("aria-current", "true");
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `pnpm --filter @csmarket/ui exec vitest run src/components/Dropdown`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```tsx
// packages/ui/src/components/Dropdown/Dropdown.tsx
"use client";

import {
  type ComponentType,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { cn } from "../../lib/cn";

export interface DropdownItem {
  key: string;
  label: ReactNode;
  href?: string;
  onSelect?: () => void;
  meta?: ReactNode;
  tone?: "default" | "danger" | "accent";
  current?: boolean;
}
export interface DropdownSeparator {
  key: string;
  separator: true;
}
export type DropdownEntry = DropdownItem | DropdownSeparator;

export interface DropdownLinkProps {
  href: string;
  className: string;
  role: "menuitem";
  tabIndex: number;
  onClick: () => void;
  children: ReactNode;
  "aria-current"?: "true";
}

export interface DropdownProps {
  label: ReactNode;
  triggerLabel?: string;
  triggerClassName?: string;
  items: DropdownEntry[];
  align?: "start" | "end";
  menuClassName?: string;
  loading?: boolean;
  status?: ReactNode;
  onOpenChange?: (open: boolean) => void;
  LinkComponent?: ComponentType<DropdownLinkProps>;
}

const isSeparator = (e: DropdownEntry): e is DropdownSeparator => "separator" in e;

function PlainLink({ children, ...props }: DropdownLinkProps) {
  return <a {...props}>{children}</a>;
}

const itemClass = (tone: DropdownItem["tone"], current: boolean | undefined) =>
  cn(
    "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-[14px] outline-none",
    "hover:bg-border-strong focus-visible:bg-border-strong",
    tone === "danger" ? "text-danger" : current || tone === "accent" ? "text-accent" : "text-fg",
  );

/**
 * A menu button (WAI-ARIA menu pattern): click / Enter / Space / ArrowDown open it, arrows,
 * Home and End move, Escape closes and returns focus, Tab or an outside press closes it.
 * Items are links (through `LinkComponent`, so an app can pass its router's Link) or actions.
 */
export function Dropdown({
  label,
  triggerLabel,
  triggerClassName,
  items,
  align = "start",
  menuClassName,
  loading = false,
  status,
  onOpenChange,
  LinkComponent = PlainLink,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const focusFirst = useRef(false);
  const id = useId();

  const setOpenState = useCallback(
    (next: boolean) => {
      setOpen(next);
      onOpenChange?.(next);
    },
    [onOpenChange],
  );

  const menuItems = (): HTMLElement[] =>
    Array.from(menu.current?.querySelectorAll<HTMLElement>("[role='menuitem']") ?? []);

  useEffect(() => {
    if (!open) return;
    if (focusFirst.current) {
      menuItems()[0]?.focus();
      focusFirst.current = false;
    }
    const onPointer = (e: PointerEvent) => {
      // A DOM node from the event target: narrowing the EventTarget to a Node.
      if (!root.current?.contains(e.target as Node)) setOpenState(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open, setOpenState]);

  const close = (refocus: boolean) => {
    setOpenState(false);
    if (refocus) trigger.current?.focus();
  };

  const onTriggerKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      focusFirst.current = true;
      setOpenState(true);
    }
  };

  const onMenuKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const list = menuItems();
    const at = list.indexOf(document.activeElement as HTMLElement); // the focused DOM element
    const move = (i: number) => {
      e.preventDefault();
      list[(i + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") move(at + 1);
    else if (e.key === "ArrowUp") move(at - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(list.length - 1);
    else if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "Tab") close(false);
  };

  return (
    <div ref={root} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={triggerLabel}
        onClick={() => setOpenState(!open)}
        onKeyDown={onTriggerKey}
        className={cn(
          "bg-surface text-fg inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[14px]",
          "focus-visible:ring-accent focus-visible:ring-offset-bg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
          triggerClassName,
        )}
      >
        {label}
      </button>
      {open && (
        <div
          ref={menu}
          id={id}
          role="menu"
          onKeyDown={onMenuKey}
          className={cn(
            "bg-surface-2 shadow-menu absolute z-50 mt-2 min-w-[200px] rounded-lg p-1.5",
            align === "end" ? "right-0" : "left-0",
            menuClassName,
          )}
        >
          {status && <p className="text-fg-muted px-3 py-2 text-[13px]">{status}</p>}
          {loading ? (
            <p role="status" className="text-fg-muted px-3 py-2 text-[13px]">
              …
            </p>
          ) : (
            items.map((entry) => {
              if (isSeparator(entry)) {
                return <hr key={entry.key} className="border-border-strong my-1" />;
              }
              const body = (
                <>
                  <span className="truncate">{entry.label}</span>
                  {entry.meta !== undefined && (
                    <span className="text-fg-muted shrink-0 text-[13px]">{entry.meta}</span>
                  )}
                </>
              );
              if (entry.href !== undefined) {
                return (
                  <LinkComponent
                    key={entry.key}
                    href={entry.href}
                    role="menuitem"
                    tabIndex={-1}
                    onClick={() => close(false)}
                    className={itemClass(entry.tone, entry.current)}
                    {...(entry.current ? { "aria-current": "true" as const } : {})}
                  >
                    {body}
                  </LinkComponent>
                );
              }
              return (
                <button
                  key={entry.key}
                  type="button"
                  role="menuitem"
                  tabIndex={-1}
                  onClick={() => {
                    entry.onSelect?.();
                    close(true);
                  }}
                  className={itemClass(entry.tone, entry.current)}
                >
                  {body}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
```

`index.ts`: `export * from "./Dropdown";`. `packages/ui/src/index.ts`: `export { Dropdown, type DropdownEntry, type DropdownItem, type DropdownLinkProps, type DropdownProps } from "./components/Dropdown";`

- [ ] **Step 4: Run tests, lint, typecheck**

Run: `pnpm --filter @csmarket/ui test && pnpm --filter @csmarket/ui lint && pnpm --filter @csmarket/ui typecheck`
Expected: PASS. (If ESLint flags the `"use client"` directive in a package, keep it — the storefront imports this from RSC files and it must be a client boundary.)

- [ ] **Step 5: Commit**

```bash
git add packages/ui
git commit -m "feat(packages/ui): dropdown menu with the WAI-ARIA menu keyboard model"
```

---

### Task 4: Accordion

**Files:**

- Create: `packages/ui/src/components/Accordion/{Accordion.tsx,Accordion.test.tsx,index.ts}`
- Modify: `packages/ui/src/index.ts`

**Interfaces:**

- Produces: `Accordion({title: ReactNode, defaultOpen?: boolean, children: ReactNode, className?: string})` — a header `<button aria-expanded aria-controls>` and a region panel (`role="region"`, `aria-labelledby`), uncontrolled.

- [ ] **Step 1: Write the failing test**

```tsx
// packages/ui/src/components/Accordion/Accordion.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Accordion } from "./Accordion";

describe("Accordion", () => {
  it("starts closed, opens on click, wires aria", () => {
    render(<Accordion title="Редкость">Covert</Accordion>);
    const head = screen.getByRole("button", { name: "Редкость" });
    expect(head).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Covert")).toBeNull();
    fireEvent.click(head);
    expect(head).toHaveAttribute("aria-expanded", "true");
    const region = screen.getByRole("region", { name: "Редкость" });
    expect(head.getAttribute("aria-controls")).toBe(region.id);
    expect(region).toHaveTextContent("Covert");
  });

  it("can start open", () => {
    render(
      <Accordion title="Качество" defaultOpen>
        FN
      </Accordion>,
    );
    expect(screen.getByText("FN")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `pnpm --filter @csmarket/ui exec vitest run src/components/Accordion`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```tsx
// packages/ui/src/components/Accordion/Accordion.tsx
"use client";

import { Minus, Plus } from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import { cn } from "../../lib/cn";

interface AccordionProps {
  title: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  children: ReactNode;
}

/** One collapsible section (filters): a header button and its region. */
export function Accordion({ title, defaultOpen = false, className, children }: AccordionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={cn("border-border border-t py-3 first:border-t-0", className)}>
      <h3>
        <button
          id={`${id}-h`}
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-p`}
          onClick={() => setOpen(!open)}
          className="text-fg focus-visible:ring-accent flex w-full items-center justify-between rounded-md text-left text-[15px] font-medium focus-visible:outline-none focus-visible:ring-2"
        >
          {title}
          {open ? (
            <Minus className="text-fg-dim size-4" aria-hidden />
          ) : (
            <Plus className="text-fg-dim size-4" aria-hidden />
          )}
        </button>
      </h3>
      {open && (
        <div id={`${id}-p`} role="region" aria-labelledby={`${id}-h`} className="mt-2">
          {children}
        </div>
      )}
    </div>
  );
}
```

`index.ts` + export in `packages/ui/src/index.ts`: `export { Accordion } from "./components/Accordion";`

- [ ] **Step 4: Run tests, lint, typecheck** — `pnpm --filter @csmarket/ui test && pnpm --filter @csmarket/ui lint && pnpm --filter @csmarket/ui typecheck` → PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ui
git commit -m "feat(packages/ui): accordion section"
```

---

### Task 5: Showcase, guide, ADR-0009

**Files:**

- Create: `apps/web/src/app/[locale]/dev/ui/page.tsx`, `apps/web/src/app/[locale]/dev/ui/page.test.tsx`
- Create: `docs/design-system.md`, `docs/decisions/0009-storefront-design-system.md`
- Modify: `AGENTS.md` §4 (one row)

**Interfaces:**

- Consumes: everything exported by `@csmarket/ui` (T2–T4).
- Produces: route `/[locale]/dev/ui` (404 when `process.env.NODE_ENV === "production"`), `robots: noindex`.

- [ ] **Step 1: Write the failing test**

```tsx
// apps/web/src/app/[locale]/dev/ui/page.test.tsx
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

import { Showcase, assertDevOnly } from "./page";

afterEach(() => vi.unstubAllEnvs());

describe("dev UI showcase", () => {
  it("is not served in production", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(() => assertDevOnly()).toThrow("NEXT_NOT_FOUND");
  });

  it("shows every token swatch and every component", () => {
    render(<Showcase />);
    for (const t of [
      "bg",
      "surface",
      "surface-2",
      "accent",
      "success",
      "danger",
      "rarity-covert",
    ]) {
      expect(screen.getByText(`--color-${t}`)).toBeInTheDocument();
    }
    for (const c of [
      "Button",
      "Chip",
      "Badge",
      "Input",
      "Select",
      "Checkbox",
      "Dropdown",
      "Accordion",
      "Panel",
    ]) {
      expect(screen.getByRole("heading", { name: c })).toBeInTheDocument();
    }
  });
});
```

- [ ] **Step 2: Run to see it fail** — `pnpm --filter @csmarket/web exec vitest run "src/app/\[locale\]/dev/ui"` → FAIL (module not found).

- [ ] **Step 3: Implement the page**

```tsx
// apps/web/src/app/[locale]/dev/ui/page.tsx
import {
  Accordion,
  Badge,
  Button,
  Checkbox,
  CheckMark,
  Chip,
  Dropdown,
  Input,
  Panel,
  Select,
} from "@csmarket/ui";
import { notFound } from "next/navigation";

import type { Metadata } from "next";

export const metadata: Metadata = { title: "UI", robots: { index: false, follow: false } };

const SWATCHES = [
  "bg",
  "surface",
  "surface-2",
  "surface-hover",
  "border",
  "border-strong",
  "fg",
  "fg-muted",
  "fg-dim",
  "accent",
  "accent-soft",
  "accent-subtle",
  "success",
  "danger",
  "warning",
  "info",
  "rarity-consumer",
  "rarity-industrial",
  "rarity-milspec",
  "rarity-restricted",
  "rarity-classified",
  "rarity-covert",
  "rarity-contraband",
  "stattrak",
] as const;

/** Throws Next's 404 in production: the showcase is a dev tool. */
export function assertDevOnly(): void {
  if (process.env.NODE_ENV === "production") notFound();
}

function Section({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-[17px] font-semibold">{name}</h2>
      <div className="flex flex-wrap items-start gap-3">{children}</div>
    </section>
  );
}

export function Showcase() {
  return (
    <main className="mx-auto max-w-[1320px] space-y-10 px-6 py-8">
      <h1 className="text-[26px] font-semibold">Design system</h1>
      <Section name="Tokens">
        {SWATCHES.map((s) => (
          <div key={s} className="w-40">
            <div
              className="border-border h-12 rounded-md border"
              style={{ background: `var(--color-${s})` }}
            />
            <p className="text-fg-muted mt-1 font-mono text-[12px]">{`--color-${s}`}</p>
          </div>
        ))}
      </Section>
      <Section name="Button">
        <Button>Войти через Steam</Button>
        <Button variant="secondary">Вторичная</Button>
        <Button variant="ghost">Тихая</Button>
        <Button variant="danger">Опасная</Button>
        <Button size="sm">Малая</Button>
        <Button disabled>Недоступна</Button>
      </Section>
      <Section name="Chip">
        <Chip active>Все</Chip>
        <Chip>Ножи</Chip>
        <Chip>Кейсы</Chip>
      </Section>
      <Section name="Badge">
        <Badge>−19%</Badge>
        <Badge tone="neutral">MW</Badge>
        <Badge tone="danger">Ошибка</Badge>
      </Section>
      <Section name="Input">
        <Input placeholder="От" className="w-40" />
        <Input placeholder="Название скина…" className="w-80" />
      </Section>
      <Section name="Select">
        <Select defaultValue="a" aria-label="Сортировка">
          <option value="a">Сначала дороже</option>
          <option value="b">Сначала дешевле</option>
        </Select>
      </Section>
      <Section name="Checkbox">
        <Checkbox>Только StatTrak™</Checkbox>
        <span className="flex items-center gap-2 text-[14px]">
          <CheckMark checked /> CheckMark
        </span>
      </Section>
      <Section name="Dropdown">
        <Dropdown
          label="Jam ▾"
          items={[
            { key: "p", label: "Профиль и трейд-ссылка", href: "#" },
            { key: "o", label: "Мои заказы", href: "#", meta: "3" },
            { key: "s", separator: true },
            { key: "x", label: "Выйти", tone: "danger", onSelect: () => undefined },
          ]}
        />
      </Section>
      <Section name="Accordion">
        <Panel className="w-64">
          <Accordion title="Качество" defaultOpen>
            <p className="text-fg-muted text-[14px]">Прямо с завода</p>
          </Accordion>
          <Accordion title="Редкость">
            <p className="text-fg-muted text-[14px]">Covert</p>
          </Accordion>
        </Panel>
      </Section>
      <Section name="Panel">
        <Panel className="w-64">Панель: фильтры, тулбар, блоки.</Panel>
      </Section>
    </main>
  );
}

export default function DevUiPage() {
  assertDevOnly();
  return <Showcase />;
}
```

(Keep each `SWATCHES` row on its own line if prettier reflows; the file must stay ≤ 300 lines.)

- [ ] **Step 4: Write the guide, the ADR and the AGENTS row**

`docs/design-system.md` — sections: «Где что лежит» (tokens.css, packages/ui, /dev/ui), the token table copied from spec §2.1, «Компоненты» (one line each: Button, Chip/chipVariants, Badge, Panel, Input, Select, Checkbox/CheckMark, Dropdown + `LinkComponent`, Accordion — when to use), «Правила» copied from spec §2.4 with the measured contrast numbers, «Как добавить компонент» (`packages/ui/src/components/<Name>/{Name.tsx,Name.test.tsx,index.ts}`, export from `src/index.ts`, add to `/dev/ui`, a line here), «Доменные компоненты» (SkinCard, SkinCategoryBar, SkinFilters, Header stay in apps/web).

`docs/decisions/0009-storefront-design-system.md` from `docs/decisions/0000-template.md`: Status Accepted, date 2026-10-04; context (amber Inter look, owner's references aim.market / skins.com); decision (tokens as single source, the palette, IBM Plex via next/font, generic components in packages/ui, domain ones in the app, a dev showcase instead of Storybook, the five rules); consequences (admin inherits the palette, other storefront pages inherit tokens before their re-layout, no new dependency); alternatives (Storybook — new dependency, rejected; per-page styling — no reuse, rejected; copying aim's exact blue accent — owner chose green).

AGENTS.md §4 table, new row after «A shared UI component»:

```
| A storefront UI element | Compose from `@csmarket/ui` and the tokens (`docs/design-system.md`); a new reusable element goes to `packages/ui`, the `/dev/ui` showcase and the guide; domain components (prices, skins) stay in `apps/web` |
```

- [ ] **Step 5: Run tests and prettier** — `pnpm --filter @csmarket/web exec vitest run "src/app/\[locale\]/dev/ui" && npx prettier --write docs/design-system.md docs/decisions/0009-storefront-design-system.md AGENTS.md "apps/web/src/app/[locale]/dev"` → PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app docs AGENTS.md
git commit -m "docs: the storefront design system — guide, ADR-0009 and a dev showcase"
```

---

### Task 6: Header — language, balance, account menu, phone menu

**Files:**

- Modify: `apps/web/src/components/Header.tsx`, `apps/web/src/components/Header.test.tsx`
- Create: `apps/web/src/components/header/{LanguageSwitcher,AccountMenu,BalanceChip,MobileMenu}.tsx` + `LanguageSwitcher.test.tsx`, `AccountMenu.test.tsx`
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json` (`web.nav`)

**Interfaces:**

- Consumes: `Dropdown`, `DropdownLinkProps` (T3); `useAuth()` → `{status, user, signInHref, signOut}`; `getBalance`, `BALANCE_KEY` (`lib/balance.ts`); `usePathname`, `getPathname`, `Link` (`@/i18n/navigation`); `formatUzs` (`@csmarket/utils`); `ORDERS`, `BALANCE`, `ACCOUNT`, `HOME` (`lib/paths.ts`).
- Produces: `LanguageSwitcher({locale})`, `AccountMenu()`, `BalanceChip({compact?: boolean})`, `MobileMenu({locale})`; `AppLink` adapter `(props: DropdownLinkProps) => <Link …/>` exported from `header/AccountMenu.tsx`.

Strings (`web.nav`), add to all three:

| key            | ru                     | uz                     | en                     |
| -------------- | ---------------------- | ---------------------- | ---------------------- |
| `catalog`      | Каталог                | Katalog                | Catalogue              |
| `orders`       | Мои заказы             | Buyurtmalarim          | My orders              |
| `language`     | Язык                   | Til                    | Language               |
| `languages.ru` | Русский                | Русский                | Русский                |
| `languages.uz` | Oʻzbekcha              | Oʻzbekcha              | Oʻzbekcha              |
| `languages.en` | English                | English                | English                |
| `menu`         | Меню                   | Menyu                  | Menu                   |
| `profile`      | Профиль и трейд-ссылка | Profil va trade-havola | Profile and trade link |
| `balance`      | Баланс и история       | Balans va tarix        | Balance and history    |
| `topUp`        | Пополнить баланс       | Balansni toʻldirish    | Top up the balance     |
| `signOut`      | Выйти                  | Chiqish                | Sign out               |

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/components/header/LanguageSwitcher.test.tsx
// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { LanguageSwitcher } from "./LanguageSwitcher";

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/category/rifles",
  getPathname: ({ href, locale }: { href: string; locale: string }) =>
    locale === "ru" ? href : `/${locale}${href}`,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("sort=price&weapon=AK-47"),
}));

describe("LanguageSwitcher", () => {
  it("keeps path and query; ru has no prefix", () => {
    render(
      <NextIntlClientProvider locale="uz" messages={{ web: ru, common }}>
        <LanguageSwitcher locale="uz" />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /UZ/ }));
    expect(screen.getByRole("menuitem", { name: "Русский" })).toHaveAttribute(
      "href",
      "/category/rifles?sort=price&weapon=AK-47",
    );
    expect(screen.getByRole("menuitem", { name: "English" })).toHaveAttribute(
      "href",
      "/en/category/rifles?sort=price&weapon=AK-47",
    );
    expect(screen.getByRole("menuitem", { name: "Oʻzbekcha" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });
});
```

```tsx
// apps/web/src/components/header/AccountMenu.test.tsx
// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { AccountMenu } from "./AccountMenu";

const signOut = vi.fn(() => Promise.resolve());
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: "signed_in",
    user: { display_name: "Jam", avatar_url: null },
    signOut,
  }),
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("AccountMenu", () => {
  it("lists profile, orders, balance and signs out", () => {
    render(
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <AccountMenu />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Jam/ }));
    expect(screen.getByRole("menuitem", { name: "Профиль и трейд-ссылка" })).toHaveAttribute(
      "href",
      "/account",
    );
    expect(screen.getByRole("menuitem", { name: "Мои заказы" })).toHaveAttribute(
      "href",
      "/account/orders",
    );
    expect(screen.getByRole("menuitem", { name: "Баланс и история" })).toHaveAttribute(
      "href",
      "/account/balance",
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "Выйти" }));
    expect(signOut).toHaveBeenCalledOnce();
  });
});
```

Update `Header.test.tsx`: keep «offers Steam sign-in to a visitor» (button now also has nav links «Каталог», «Мои заказы» — assert both exist as links with `href` `/` and `/account/orders`); replace «links a signed-in user to their account» with «shows the balance chip and the account menu to a signed-in user» (mock `@tanstack/react-query`'s `useQuery` → `{ data: { balance_uzs: "1250000" } }`, assert text matching `/1\s250\s000/` and a button named `/Jam/`). Mock `./header/LanguageSwitcher` to a stub (`() => <span>lang</span>`) in this file.

- [ ] **Step 2: Run to see them fail** — `pnpm --filter @csmarket/web exec vitest run src/components/Header.test.tsx src/components/header` → FAIL.

- [ ] **Step 3: Implement**

```tsx
// apps/web/src/components/header/LanguageSwitcher.tsx
"use client";

import { LOCALES } from "@csmarket/i18n";
import { Dropdown } from "@csmarket/ui";
import { Globe } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { getPathname, usePathname } from "@/i18n/navigation";

/** Links to the same page in each language (path and query kept); the profile is untouched. */
export function LanguageSwitcher({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const tail = search ? `?${search}` : "";
  return (
    <Dropdown
      align="end"
      triggerLabel={`${t("language")}: ${locale.toUpperCase()}`}
      label={
        <>
          <Globe className="size-4" aria-hidden />
          {locale.toUpperCase()}
        </>
      }
      items={LOCALES.map((l) => ({
        key: l,
        label: t(`languages.${l}`),
        href: getPathname({ href: pathname, locale: l }) + tail,
        current: l === locale,
      }))}
    />
  );
}
```

(If `getPathname`'s typed `href` rejects a plain string, pass `{ href: { pathname } }` per next-intl's typed routing — check `@/i18n/routing`, which defines no `pathnames`, so a string is accepted.)

```tsx
// apps/web/src/components/header/AccountMenu.tsx
"use client";

import { Dropdown, type DropdownLinkProps } from "@csmarket/ui";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { ACCOUNT, BALANCE, ORDERS } from "@/lib/paths";

/** next-intl's locale-aware Link, shaped for `Dropdown`. */
export function AppLink({ href, children, ...rest }: DropdownLinkProps) {
  return (
    <Link href={href} {...rest}>
      {children}
    </Link>
  );
}

export function AccountMenu() {
  const t = useTranslations("web.nav");
  const { user, signOut } = useAuth();
  if (!user) return null;
  return (
    <Dropdown
      align="end"
      LinkComponent={AppLink}
      triggerClassName="py-1.5 pl-1.5"
      label={
        <>
          {user.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- Steam CDN avatars; next/image would need remotePatterns per CDN host
            <img src={user.avatar_url} alt="" width={28} height={28} className="rounded-md" />
          ) : (
            <span aria-hidden className="bg-accent/30 size-7 rounded-md" />
          )}
          <span className="max-w-[120px] truncate">{user.display_name ?? t("account")}</span>
          <ChevronDown className="text-fg-dim size-4" aria-hidden />
        </>
      }
      items={[
        { key: "profile", label: t("profile"), href: ACCOUNT },
        { key: "orders", label: t("orders"), href: ORDERS },
        { key: "balance", label: t("balance"), href: BALANCE },
        { key: "sep", separator: true },
        { key: "out", label: t("signOut"), tone: "danger", onSelect: () => void signOut() },
      ]}
    />
  );
}
```

```tsx
// apps/web/src/components/header/BalanceChip.tsx
"use client";

import { formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { BALANCE_KEY, getBalance } from "@/lib/balance";
import { BALANCE } from "@/lib/paths";

/** The signed-in balance with a «+» to top up; `compact` drops the «сум» on phones. */
export function BalanceChip({ compact = false }: { compact?: boolean }) {
  const t = useTranslations("web.nav");
  const locale = useLocale();
  const balance = useQuery({ queryKey: BALANCE_KEY, queryFn: getBalance });
  const amount = balance.data?.balance_uzs;
  return (
    <span className="bg-surface flex items-center gap-2.5 rounded-lg py-1.5 pl-3.5 pr-1.5 text-[14px] font-semibold">
      <span className="num">
        {amount === undefined
          ? "…"
          : compact
            ? formatUzs(locale, amount).replace(/\s\D+$/, "")
            : formatUzs(locale, amount)}
      </span>
      <Link
        href={BALANCE}
        aria-label={t("topUp")}
        className="bg-accent text-accent-fg hover:bg-accent-hover focus-visible:ring-accent focus-visible:ring-offset-bg flex size-7 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
      >
        <Plus className="size-4" strokeWidth={3} aria-hidden />
      </Link>
    </span>
  );
}
```

(Check `Balance`'s field name in `lib/balance.ts` (`interface Balance`); use it verbatim if it is not `balance_uzs`.)

```tsx
// apps/web/src/components/header/MobileMenu.tsx
"use client";

import { LOCALES } from "@csmarket/i18n";
import { Dropdown, type DropdownEntry } from "@csmarket/ui";
import { Menu } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { AppLink } from "./AccountMenu";

import { getPathname, usePathname } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { ACCOUNT, BALANCE, HOME, ORDERS } from "@/lib/paths";

/** Phones: one ☰ menu with the nav, the languages and the account. */
export function MobileMenu({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const { status, signInHref, signOut } = useAuth();
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const tail = search ? `?${search}` : "";
  const items: DropdownEntry[] = [
    { key: "catalog", label: t("catalog"), href: HOME },
    { key: "orders", label: t("orders"), href: ORDERS },
    { key: "s1", separator: true },
    ...LOCALES.map((l) => ({
      key: `lang-${l}`,
      label: t(`languages.${l}`),
      href: getPathname({ href: pathname, locale: l }) + tail,
      current: l === locale,
    })),
    { key: "s2", separator: true },
    ...(status === "signed_in"
      ? [
          { key: "profile", label: t("profile"), href: ACCOUNT },
          { key: "balance", label: t("balance"), href: BALANCE },
          {
            key: "out",
            label: t("signOut"),
            tone: "danger" as const,
            onSelect: () => void signOut(),
          },
        ]
      : [{ key: "in", label: t("signIn"), href: signInHref(locale), tone: "accent" as const }]),
  ];
  return (
    <Dropdown
      align="end"
      triggerLabel={t("menu")}
      triggerClassName="size-10 justify-center px-0"
      menuClassName="w-[calc(100vw-2rem)] max-w-sm"
      LinkComponent={AppLink}
      label={<Menu className="size-5" aria-hidden />}
      items={items}
    />
  );
}
```

Note: the language links are absolute paths already prefixed by `getPathname`; `AppLink` (next-intl `Link`) would re-prefix them — so for the language entries in `MobileMenu`, render them as plain anchors: give `Dropdown` the default link for those by splitting into two Dropdown-free sections is overkill; instead build those hrefs with `getPathname` and set `locale` on next-intl `Link`. Implement `AppLink` to accept an optional `data-locale` in the href? Simplest correct approach: keep `LinkComponent={AppLink}` and make the language entries `onSelect: () => { window.location.assign(getPathname({ href: pathname, locale: l }) + tail) }` (no `href`) — a full navigation, which a locale switch needs anyway. Use the same `onSelect` form in `LanguageSwitcher` only if its test (which asserts `href`) is changed accordingly; keep `LanguageSwitcher` on plain `<a>` (no `LinkComponent`) as written above.

```tsx
// apps/web/src/components/Header.tsx
"use client";

import { buttonVariants } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import { AccountMenu } from "./header/AccountMenu";
import { BalanceChip } from "./header/BalanceChip";
import { LanguageSwitcher } from "./header/LanguageSwitcher";
import { MobileMenu } from "./header/MobileMenu";

import { Link, usePathname } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { HOME, ORDERS } from "@/lib/paths";

interface HeaderProps {
  locale: string;
}

const navClass = (on: boolean) =>
  `text-[15px] transition-colors ${on ? "text-fg" : "text-fg-dim hover:text-fg"}`;

/** Logo, nav, language and the account; on phones a balance and a ☰ menu. */
export function Header({ locale }: HeaderProps) {
  const t = useTranslations("web.nav");
  const { status } = useAuth();
  const pathname = usePathname();
  const signedIn = status === "signed_in";
  return (
    <header className="mx-auto flex h-[68px] max-w-[1320px] items-center gap-8 px-4 sm:px-6">
      <Link href={HOME} className="text-[22px] font-bold tracking-tight" aria-label="csmarket">
        cs<span className="text-accent">market</span>
      </Link>
      <nav className="hidden items-center gap-6 md:flex">
        <Link href={HOME} className={navClass(pathname === HOME)}>
          {t("catalog")}
        </Link>
        <Link href={ORDERS} className={navClass(pathname.startsWith(ORDERS))}>
          {t("orders")}
        </Link>
      </nav>
      <div className="ml-auto flex items-center gap-2.5">
        <div className="hidden md:block">
          <LanguageSwitcher locale={locale} />
        </div>
        {status === "loading" ? (
          <span aria-hidden className="bg-surface h-10 w-40 animate-pulse rounded-lg" />
        ) : signedIn ? (
          <>
            <span className="hidden md:block">
              <BalanceChip />
            </span>
            <span className="md:hidden">
              <BalanceChip compact />
            </span>
            <span className="hidden md:block">
              <AccountMenu />
            </span>
          </>
        ) : (
          <SignIn locale={locale} />
        )}
        <span className="md:hidden">
          <MobileMenu locale={locale} />
        </span>
      </div>
    </header>
  );
}

function SignIn({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const { signInHref } = useAuth();
  return (
    <a
      href={signInHref(locale)}
      className={buttonVariants({ size: "md" }) + " hidden md:inline-flex"}
    >
      {t("signIn")}
    </a>
  );
}
```

`Header` becomes a client component (it already used `useAuth`); keep its import in `layout.tsx`. Wrap `<Header>` in `<Suspense>` in `layout.tsx` because `useSearchParams` inside the switcher needs a boundary for static pages:

```tsx
import { Suspense } from "react";
…
            <Suspense fallback={<div className="h-[68px]" />}>
              <Header locale={locale} />
            </Suspense>
```

- [ ] **Step 4: Run tests, lint, typecheck, i18n parity**

Run: `pnpm --filter @csmarket/web exec vitest run src/components/Header.test.tsx src/components/header && pnpm --filter @csmarket/i18n test && pnpm exec turbo run lint typecheck --filter=@csmarket/web`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web packages/i18n
git commit -m "feat(web/header): navigation, language switcher, balance chip and account menu"
```

---

### Task 7: SkinCard — variant B

**Files:**

- Modify: `apps/web/src/components/skins/SkinCard.tsx`, `SkinCard.test.tsx`
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json` (`web.skins.steamHigher`)

**Interfaces:**

- Consumes: `Badge` (T2); `SkinItem` fields `exterior, stattrak, souvenir, count, discount_percent, rarity_color, weapon, skin, phase, image_url, price_uzs, price_usd`; `t("pieces", {count})` exists.
- Produces: unchanged signature `SkinCard({item, locale})`.

Strings: `steamHigher` — ru «Steam дороже на {percent}%», uz «Steamʼda {percent}% qimmatroq», en «{percent}% more on Steam».

- [ ] **Step 1: Write the failing test** (add to `SkinCard.test.tsx`, reusing its render helper and item fixture; set `discount_percent: 19, exterior: "MW", count: 3, stattrak: true`)

```tsx
it("variant B: wear, ST™, pieces, discount badge, green price and the Steam line", () => {
  renderCard({ ...item, discount_percent: 19, exterior: "MW", count: 3, stattrak: true });
  const card = screen.getByRole("link");
  expect(within(card).getByText("MW")).toBeInTheDocument();
  expect(within(card).getByText("ST™")).toBeInTheDocument();
  expect(within(card).getByText("3 шт.")).toBeInTheDocument();
  expect(within(card).getByText("−19%")).toBeInTheDocument();
  expect(within(card).getByText("Steam дороже на 19%")).toBeInTheDocument();
  expect(card.querySelector(".text-accent.num")).not.toBeNull();
});

it("no Steam line and no badge under 5 %", () => {
  renderCard({ ...item, discount_percent: 3 });
  expect(screen.queryByText(/Steam дороже/)).toBeNull();
  expect(screen.queryByText("−3%")).toBeNull();
});
```

(Adapt the helper name to the file's existing one; the existing «under 5 % a badge only dilutes» rule stays — spec's «> 0» is superseded by this earlier owner-visible rule, ledger it.)

- [ ] **Step 2: Run to see it fail** — `pnpm --filter @csmarket/web exec vitest run src/components/skins/SkinCard.test.tsx` → FAIL.

- [ ] **Step 3: Implement**

```tsx
// apps/web/src/components/skins/SkinCard.tsx — the JSX returned
<Link
  href={itemPath(item.slug)}
  className="bg-surface hover:bg-surface-hover hover:border-border focus-visible:ring-accent focus-visible:ring-offset-bg group relative flex h-full flex-col rounded-lg border border-transparent px-3 pb-3 pt-2.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
>
  <div className="text-fg-dim flex items-center gap-1.5 text-[11px]">
    {item.exterior && <span>{item.exterior}</span>}
    {item.stattrak && <span className="text-stattrak font-semibold">ST™</span>}
    {item.souvenir && <span className="text-rarity-contraband font-semibold">SV</span>}
    <span className="ml-auto">{t("pieces", { count: item.count })}</span>
  </div>
  {discount !== null && <Badge className="absolute right-3 top-8">−{discount}%</Badge>}
  <div className="relative my-1 aspect-[4/3] w-full">
    {glow && <span aria-hidden className="absolute inset-0" style={{ background: glow }} />}
    {item.image_url && (
      <Image
        src={steamImageSize(item.image_url, "256fx256f")}
        alt={item.name}
        fill
        unoptimized
        sizes="(min-width: 1280px) 20vw, (min-width: 640px) 33vw, 50vw"
        className="object-contain p-2 transition duration-300 group-hover:scale-[1.04]"
      />
    )}
  </div>
  {item.weapon && <div className="text-fg-dim truncate text-[12px]">{item.weapon}</div>}
  <div className="truncate text-[13px] font-medium">
    {isVanilla(item) ? t("vanilla") : (item.skin ?? item.name)}
    {item.phase && <span className="text-fg-dim"> · {item.phase}</span>}
  </div>
  <div className="mt-auto pt-2">
    {price ? (
      <span className="text-accent num text-[14px] font-semibold">{price}</span>
    ) : (
      <span className="text-fg-dim text-[12px]">{t("soldOut")}</span>
    )}
    {discount !== null && (
      <p className="text-fg-dim mt-0.5 text-[11px]">{t("steamHigher", { percent: discount })}</p>
    )}
  </div>
</Link>
```

Import `Badge` from `@csmarket/ui`. Make `rarityGlow` (in `@csmarket/utils/skins`) a radial «60% 55% at 50% 60%, {color}55, transparent 70%» if its current gradient differs — check its test first and update both together. Update the doc comment: «the rarity glows behind the art».

- [ ] **Step 4: Run** — `pnpm --filter @csmarket/web exec vitest run src/components/skins && pnpm --filter @csmarket/utils test && pnpm --filter @csmarket/i18n test` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web packages/i18n packages/utils
git commit -m "feat(web/skins): catalogue card variant B — wear, pieces, discount and the Steam line"
```

---

### Task 8: Category chips with silhouettes and the model menu

**Files:**

- Modify: `apps/web/src/components/skins/SkinCategoryBar.tsx`, `SkinCategoryBar.test.tsx`, `SkinCategoryIcon.tsx` (size prop)
- Create: `apps/web/src/components/skins/WeaponMenu.tsx`, `WeaponMenu.test.tsx`
- Modify: `apps/web/src/lib/skins.ts` (`fetchSkinFacets`)
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json` (`web.skins.allOf.*`, `web.skins.models`, `web.skins.modelsFailed`)

**Interfaces:**

- Consumes: `chipVariants` (T2), `Dropdown` (T3), `AppLink` (T6), `SKIN_CATEGORIES`, `skinQueryString`, `SkinFacets`, `SkinQuery`.
- Produces: `fetchSkinFacets(category: string, signal?: AbortSignal): Promise<SkinFacets>` (browser fetch of `${API_BASE}/api/v1/skins/facets?category=`); `SkinCategoryIcon({category, size?: "sm" | "md"})`; `WeaponMenu({category, query, label, initial?: {value:string;count:number}[]})`.

Order of chips: `["all", "knives", "gloves", "rifles", "pistols", "smgs", "heavy", "agents", "cases", "keys", "charms", "music-kits"]`, filtered by `facets.categories` presence (as today). Weapon categories (with a menu): `knives, gloves, rifles, pistols, smgs, heavy`.

Strings: `allOf` ru {knives «Все ножи», gloves «Все перчатки», rifles «Все винтовки», pistols «Все пистолеты», smgs «Все пистолеты-пулемёты», heavy «Всё тяжёлое оружие»}; uz {«Barcha pichoqlar», «Barcha qoʻlqoplar», «Barcha miltiqlar», «Barcha toʻpponchalar», «Barcha pistolet-pulemyotlar», «Barcha ogʻir qurollar»}; en {«All knives», «All gloves», «All rifles», «All pistols», «All SMGs», «All heavy»}. `models` ru «Модели: {category}», uz «Modellar: {category}», en «Models: {category}». `modelsFailed` ru «Не удалось загрузить модели», uz «Modellarni yuklab boʻlmadi», en «Could not load the models».

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/components/skins/WeaponMenu.test.tsx
// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WeaponMenu } from "./WeaponMenu";

const fetchFacets = vi.hoisted(() => vi.fn());
vi.mock("@/lib/skins", () => ({ fetchSkinFacets: fetchFacets }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const query = { sort: "-price" as const };

function renderMenu() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <WeaponMenu category="rifles" label="Винтовки" query={query} />
    </NextIntlClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Модели: Винтовки" }));
}

describe("WeaponMenu", () => {
  beforeEach(() => fetchFacets.mockReset());

  it("loads the models on first open and links each", async () => {
    fetchFacets.mockResolvedValue({
      weapons: [
        { value: "AK-47", count: 412 },
        { value: "AWP", count: 326 },
      ],
    });
    renderMenu();
    const ak = await screen.findByRole("menuitem", { name: /AK-47/ });
    expect(ak.getAttribute("href")).toContain("category=rifles");
    expect(ak.getAttribute("href")).toContain("weapon=AK-47");
    expect(screen.getByText("412")).toBeInTheDocument();
    const all = screen.getByRole("menuitem", { name: "Все винтовки" });
    expect(all.getAttribute("href")).not.toContain("weapon=");
    expect(fetchFacets).toHaveBeenCalledWith("rifles", expect.any(AbortSignal));
  });

  it("failed load still offers the category and says so", async () => {
    fetchFacets.mockRejectedValue(new Error("down"));
    renderMenu();
    expect(await screen.findByText("Не удалось загрузить модели")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Все винтовки" })).toBeInTheDocument();
  });
});
```

Add to `SkinCategoryBar.test.tsx` (it renders the server component with facets; mock `./WeaponMenu` to `({ label }: { label: string }) => <button>{`menu:${label}`}</button>`):

```tsx
it("chips carry silhouettes, knives first, and weapon categories get a model menu", () => {
  renderBar({ sort: "-price" }, facetsWith(["rifles", "knives", "cases"]));
  const links = screen.getAllByRole("link").map((a) => a.textContent);
  expect(links).toEqual(["Все", "Ножи", "Винтовки", "Кейсы"]);
  expect(screen.getByRole("button", { name: "menu:Ножи" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "menu:Кейсы" })).toBeNull();
  expect(document.querySelectorAll("[data-skin-icon]").length).toBeGreaterThanOrEqual(3);
});

it("unknown model stays clearable: the chip shows it and links back to the category", () => {
  renderBar({ sort: "-price", category: "rifles", weapon: "Foo" }, facetsWith(["rifles"]));
  const chip = screen.getByRole("link", { name: /Foo/ });
  expect(chip).toHaveAttribute("aria-current", "page");
  expect(chip.getAttribute("href")).not.toContain("weapon=");
});
```

(Use the file's existing render helper and facets fixture; add `facetsWith(cats)` returning `{categories: cats.map(v=>({value:v,count:1})), weapons: [], exteriors: [], rarities: [], teams: []}` if absent.)

- [ ] **Step 2: Run to see them fail** — `pnpm --filter @csmarket/web exec vitest run src/components/skins/SkinCategoryBar.test.tsx src/components/skins/WeaponMenu.test.tsx` → FAIL.

- [ ] **Step 3: Implement**

```ts
// apps/web/src/lib/skins.ts — append
/** Browser read of the facets inside a category (the model menu); throws on any failure. */
export async function fetchSkinFacets(category: string, signal?: AbortSignal): Promise<SkinFacets> {
  const qs = new URLSearchParams({ category }).toString();
  const res = await fetch(`${API_BASE}/api/v1/skins/facets?${qs}`, { signal });
  if (!res.ok) throw new Error(`facets ${res.status.toString()}`);
  return (await res.json()) as SkinFacets; // known-shape JSON from our own API
}
```

(Import `API_BASE` from `./api` if `lib/skins.ts` does not already have the browser base; follow `fetchSkinsPage`'s pattern in the same file instead if it differs.)

```tsx
// apps/web/src/components/skins/WeaponMenu.tsx
"use client";

import { skinQueryString } from "@csmarket/utils/skins";
import { Dropdown, type DropdownEntry } from "@csmarket/ui";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import type { SkinCategory, SkinQuery } from "@csmarket/utils/skins";

import { AppLink } from "@/components/header/AccountMenu";
import { fetchSkinFacets } from "@/lib/skins";
import { HOME } from "@/lib/paths";

interface Model {
  value: string;
  count: number;
}

interface WeaponMenuProps {
  category: SkinCategory;
  label: string;
  query: SkinQuery;
  /** The models already known (the active category's facets): no request on open. */
  initial?: Model[];
}

/** The ▾ beside a weapon category chip: «Все …» and the category's models with counts. */
export function WeaponMenu({ category, label, query, initial }: WeaponMenuProps) {
  const t = useTranslations("web.skins");
  const [models, setModels] = useState<Model[] | null>(initial ?? null);
  const [failed, setFailed] = useState(false);
  const inflight = useRef<AbortController | null>(null);

  const load = (open: boolean) => {
    if (!open || models !== null || inflight.current) return;
    const ctrl = new AbortController();
    inflight.current = ctrl;
    setFailed(false);
    fetchSkinFacets(category, ctrl.signal)
      .then((f) => setModels(f.weapons))
      .catch(() => setFailed(true))
      .finally(() => {
        inflight.current = null;
      });
  };

  const href = (weapon: string | undefined) => HOME + skinQueryString(query, { category, weapon });
  const items: DropdownEntry[] = [
    { key: "__all", label: t(`allOf.${category}`), href: href(undefined), tone: "accent" },
    ...(models ?? []).map((m) => ({
      key: m.value,
      label: m.value,
      meta: m.count,
      href: href(m.value),
      current: query.category === category && query.weapon === m.value,
    })),
  ];

  return (
    <Dropdown
      triggerLabel={t("models", { category: label })}
      triggerClassName="h-full rounded-l-none bg-transparent px-2 text-inherit"
      label={<ChevronDown className="size-3.5" aria-hidden />}
      LinkComponent={AppLink}
      items={items}
      loading={models === null && !failed}
      status={failed ? t("modelsFailed") : undefined}
      onOpenChange={load}
      menuClassName="max-h-[360px] overflow-y-auto"
    />
  );
}
```

Note: with `loading` the Dropdown hides items; to honour «failed load still offers the category», `loading` is false once `failed` (the «Все …» item renders with the status line above it).

`SkinCategoryIcon`: add `size?: "sm" | "md"` (default `"md"` = today's sizes); `"sm"` → `h-[14px]`, width `w-[26px]` wide / `w-[16px]` narrow; the `all` glyph `h-3.5 w-3.5`.

```tsx
// apps/web/src/components/skins/SkinCategoryBar.tsx
import { SKIN_CATEGORIES, skinQueryString } from "@csmarket/utils/skins";
import { chipVariants } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import { ScrollActiveIntoView } from "./ScrollActiveIntoView";
import { SkinCategoryIcon } from "./SkinCategoryIcon";
import { WeaponMenu } from "./WeaponMenu";

import type { SkinCategory, SkinFacets, SkinQuery, SkinQueryPatch } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { HOME } from "@/lib/paths";

const ORDER: SkinCategory[] = [
  "knives",
  "gloves",
  "rifles",
  "pistols",
  "smgs",
  "heavy",
  "agents",
  "cases",
  "keys",
  "charms",
  "music-kits",
];
const WITH_MODELS: ReadonlySet<SkinCategory> = new Set([
  "knives",
  "gloves",
  "rifles",
  "pistols",
  "smgs",
  "heavy",
]);

/**
 * Categories as chips with their silhouette (plain links — crawlable, no JS); weapon
 * categories add a ▾ menu of models (`WeaponMenu`, loaded on first open). With a model
 * chosen the active chip names it and links back to the whole category.
 */
export function SkinCategoryBar({ query, facets }: { query: SkinQuery; facets: SkinFacets }) {
  const t = useTranslations("web.skins");
  const present = new Set(facets.categories.map((f) => f.value));
  const categories = ORDER.filter(
    (c) => present.has(c) && (SKIN_CATEGORIES as readonly string[]).includes(c),
  );
  const href = (patch: SkinQueryPatch) => HOME + skinQueryString(query, patch);

  return (
    <ScrollActiveIntoView
      activeKey={query.category ?? ""}
      className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:flex-wrap lg:overflow-visible"
    >
      <Link
        href={href({ category: undefined, weapon: undefined })}
        className={chipVariants({ active: !query.category })}
        aria-current={!query.category ? "page" : undefined}
      >
        <SkinCategoryIcon category="all" size="sm" />
        {t("all")}
      </Link>
      {categories.map((c) => {
        const active = query.category === c;
        const label = t(`category.${c}`);
        const menu = WITH_MODELS.has(c);
        return (
          <span key={c} className={`${chipVariants({ active })} gap-0 p-0 ${menu ? "" : ""}`}>
            <Link
              href={href({ category: c, weapon: undefined })}
              className={`flex items-center gap-2 py-2 pl-3.5 ${menu ? "pr-1" : "pr-3.5"} focus-visible:ring-accent rounded-md focus-visible:outline-none focus-visible:ring-2`}
              aria-current={active ? "page" : undefined}
            >
              <SkinCategoryIcon category={c} size="sm" />
              {active && query.weapon ? `${label} · ${query.weapon}` : label}
            </Link>
            {menu && (
              <WeaponMenu
                category={c}
                label={label}
                query={query}
                {...(active ? { initial: facets.weapons } : {})}
              />
            )}
          </span>
        );
      })}
    </ScrollActiveIntoView>
  );
}
```

(The second «weapons» chip row is removed — the menu replaces it; weapon landing pages keep crawlable model links. Strip the empty `${menu ? "" : ""}` when typing it in. If `ScrollActiveIntoView` requires direct children with `data-key`, keep its existing contract.)

- [ ] **Step 4: Run** — `pnpm --filter @csmarket/web exec vitest run src/components/skins && pnpm --filter @csmarket/i18n test && pnpm exec turbo run lint typecheck --filter=@csmarket/web` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web packages/i18n
git commit -m "feat(web/skins): category chips with silhouettes and a lazily loaded model menu"
```

---

### Task 9: Filters as accordions and the catalogue composition

**Files:**

- Modify: `apps/web/src/components/skins/SkinFilters.tsx`, `SkinFilters.test.tsx`, `SkinPriceFilter.tsx`, `SkinSort.tsx`, `SkinSearch.tsx` (classes only), `apps/web/src/app/[locale]/page.tsx`
- Test: `SkinFilters.test.tsx`, a new `apps/web/src/app/[locale]/page.layout.test.tsx` is not needed — layout is checked by the Task 10 screenshots.

**Interfaces:**

- Consumes: `Accordion`, `CheckMark`, `Panel`, `inputClass`, `selectClass` (T2–T4).

- [ ] **Step 1: Write the failing test** (add to `SkinFilters.test.tsx`; mock `@csmarket/ui`'s `Accordion` is not needed — it is a real client component, render in jsdom)

```tsx
it("sections are accordions: wear opens by default, an active rarity opens its own", () => {
  renderFilters({ sort: "-price", rarity: "Covert" }, facets);
  expect(screen.getByRole("button", { name: /Качество/ })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: /Редкость/ })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: /Цена/ })).toHaveAttribute("aria-expanded", "true");
});

it("an untouched rarity section starts closed", () => {
  renderFilters({ sort: "-price" }, facets);
  expect(screen.getByRole("button", { name: /Редкость/ })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});
```

(Use the file's helper names; the labels come from `t("wear")`, `t("rarity")`, `t("price")`.)

- [ ] **Step 2: Run to see it fail** — `pnpm --filter @csmarket/web exec vitest run src/components/skins/SkinFilters.test.tsx` → FAIL.

- [ ] **Step 3: Implement**

In `SkinFilters`: wrap «Цена» (`SkinPriceFilter`) in `<Accordion title={t("price")} defaultOpen>`; team in `<Accordion title={t("team.title")} defaultOpen={query.team !== undefined}>`; wear in `<Accordion title={t("wear")} defaultOpen>`; rarity in `<Accordion title={t("rarity")} defaultOpen={query.rarity !== undefined}>`; StatTrak in `<Accordion title={t("stattrak")} defaultOpen={query.stattrak === true}>`. Replace the local `Check` with `CheckMark` from `@csmarket/ui`. Wear rows: label left, the code (`e`) right in `text-fg-dim text-[12px]`. Option class:

```ts
function option(active: boolean): string {
  return `flex items-center gap-2.5 rounded-md px-1 py-1.5 text-[14px] transition-colors ${
    active ? "text-fg" : "text-fg-muted hover:text-fg"
  }`;
}
```

Reset link: `buttonVariants({ variant: "secondary", size: "sm" })` + `mt-4 w-full`. Remove the uppercase section labels (the Accordion titles replace them).

`SkinPriceFilter`, `SkinSearch`, `SkinSort`: replace their field classes with `inputClass` / `selectClass` (`SkinSort`'s `<select>` gets `selectClass + " w-[190px]"`; search input `inputClass` with the left icon padding it already has).

`page.tsx` — the returned JSX becomes:

```tsx
<main id="main-content" className="mx-auto max-w-[1320px] px-4 pb-28 pt-2 sm:px-6">
  <h1 className="mb-5 text-center text-[26px] font-semibold">{t("title")}</h1>
  <Panel className="mb-3 flex flex-col gap-2.5 p-3 sm:flex-row">
    <SkinSearch initial={query.q ?? ""} locale={locale} query={query} />
    <div className="flex gap-2">
      {facets && (
        <SkinFilterDrawer count={activeFilterCount(query)}>
          <SkinFilters query={query} facets={facets} />
        </SkinFilterDrawer>
      )}
      <SkinSort query={query} />
    </div>
  </Panel>
  <div className="lg:flex lg:gap-3">
    {facets && (
      <aside className="hidden lg:block lg:w-[250px] lg:shrink-0">
        <Panel className="sticky top-4">
          <p className="mb-2 flex items-center gap-2 text-[17px] font-semibold">
            <SlidersHorizontal className="size-4" aria-hidden />
            {t("filters")}
          </p>
          <SkinFilters query={query} facets={facets} />
        </Panel>
      </aside>
    )}
    <section className="min-w-0 flex-1">
      {facets && <SkinCategoryBar query={query} facets={facets} />}
      {/* empty state and grid exactly as before, with the grid classes: */}
      {/* "mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5" */}…
    </section>
  </div>
</main>
```

Keep the empty state, `SkinGridMore` and `SkinLandingLinks` blocks verbatim inside `<section>`; only the `<ul>` class changes to `mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5`. Import `Panel` from `@csmarket/ui` and `SlidersHorizontal` from `lucide-react`. Apply the same composition to `category/[category]/page.tsx` and `weapon/[weapon]/page.tsx` only if they render the same grid block (check; if they use a shared component, it inherits).

- [ ] **Step 4: Run** — `pnpm --filter @csmarket/web test && pnpm exec turbo run lint typecheck --filter=@csmarket/web && NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "feat(web/skins): catalogue composition — toolbar panel, accordion filters, five-column grid"
```

---

### Task 10: Visual check, e2e and the final gate

**Files:**

- Create: `e2e/tests/design.spec.ts`
- Modify: `e2e/playwright.config.ts` (add `design` to `web-chromium` and to `web-iphone` testMatch), existing specs only where a role/label moved
- Modify: `e2e/README.md`

- [ ] **Step 1: Write the spec**

```ts
// e2e/tests/design.spec.ts
import { expect, test } from "@playwright/test";

test("catalogue: chips with a model menu, cards in the new style", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Скины КС2 (CS2)");
  const rifles = page.getByRole("button", { name: "Модели: Винтовки" });
  await rifles.click();
  const ak = page.getByRole("menuitem", { name: /AK-47/ });
  await expect(ak).toBeVisible();
  await ak.click();
  await expect(page).toHaveURL(/category=rifles/);
  await expect(page).toHaveURL(/weapon=AK-47/);
  await expect(page.getByRole("link", { name: /Винтовки · AK-47/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("language switch keeps the page and the filters", async ({ page, isMobile }) => {
  test.skip(isMobile, "desktop switcher");
  await page.goto("/?category=knives");
  await page.getByRole("button", { name: /Язык/ }).click();
  await page.getByRole("menuitem", { name: "English" }).click();
  await expect(page).toHaveURL(/\/en\/?\?category=knives/);
});

test("no horizontal overflow at 390", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await expect(page.getByRole("button", { name: "Меню" })).toBeVisible();
});
```

- [ ] **Step 2: Run the dev stack and the e2e suite**

```bash
docker compose up -d && make migrate && make seed-skins
make test-e2e
```

Expected: all specs pass. Where an existing spec fails only because a role or label moved (the header link «Войти через Steam» is still a link; the category tiles became chips — same link names), update the selector, not the assertion; a real regression is fixed in the app.

- [ ] **Step 3: Screenshots against the mockups**

With Playwright (MCP or a one-off script), capture at 1440×900 and 390×844: `/` as a guest; `/` with «Модели: Винтовки» open; `/` signed in (dev login) with the account menu open. Save under `.playwright-mcp/design-*.png` (git-ignored) and compare with `.superpowers/brainstorm/40350-1791072859/content/{card.html,catalog-v2.html,header.html}`. Any visible drift from the mockup (spacing, colour, order) is fixed before the gate.

- [ ] **Step 4: Full gate**

```bash
make lint typecheck test
npx prettier --check .
bash scripts/check-no-yupay.sh
docker compose down
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add e2e
git commit -m "test(e2e): the design system on the catalogue — model menu, language switch, phone width"
```

---

## Self-review (done while writing)

- **Spec coverage:** tokens §2.1 → T1; components §2.2 → T2 (Button, Chip, Badge, Panel, Input, Select, Checkbox), T3 (Dropdown), T4 (Accordion); guide/showcase/ADR §2.3 → T5; rules §2.4 → T1 contrast test + guide; header §3 → T6; catalogue §4: title/toolbar/filters/grid → T9, chips/model menu → T8, card → T7; strings → T6–T8; testing §5 → each task + T10. Admin side effect is passive (T1).
- **Placeholders:** none; steps that depend on an existing helper name say which file to read for it.
- **Type consistency:** `Dropdown` props (`items`, `LinkComponent`, `onOpenChange`, `loading`, `status`, `triggerLabel`) used identically in T5, T6, T8; `AppLink` defined in T6, consumed in T8; `fetchSkinFacets(category, signal)` T8 only; `chipVariants({active})` T2 → T8; `CheckMark({checked})` T2 → T9; `SkinCategoryIcon({category, size})` T8.
- **Review Focus → tests:** 1 → T3 keyboard/escape/tab tests; 2 → T8 «failed load still offers the category»; 3 → T6 LanguageSwitcher «keeps path and query»; 4 → T8 «unknown model stays clearable»; 5 → T10 «no horizontal overflow at 390».
