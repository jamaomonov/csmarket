# 0020. recharts for the admin analytics charts

- **Status**: Accepted
- **Date**: 2026-10-19
- **Deciders**: owner
- **Tags**: frontend | admin

## Context and problem statement

The admin «Аналитика» page (spec `2026-10-19-analytics-design.md`) shows profit by day — earned
and in-flight bars with a revenue line on a second axis, a tooltip per day. The admin has no
chart library. YuPay's analytics, which the owner asked to match, uses recharts.

## Decision drivers

- A by-day composed chart (stacked bars + a line, two axes, tooltip) without hand-rolled SVG.
- React 19 support; typed props.
- The storefront must not pay for it; the other admin pages neither.

## Considered options

1. **recharts 2.15** — declarative React components, React 19 from 2.15, used in YuPay.
2. **Hand-written SVG** — no dependency, but axes, ticks, tooltips and resizing to maintain.
3. **Chart.js / ECharts** — imperative canvas libraries behind wrappers, heavier.

## Decision outcome

**Chosen option:** recharts `2.15.4`, in `apps/admin` only. Only
`features/analytics/charts/` imports it, and the page is lazy-loaded (`React.lazy`), so the
other admin pages do not load it. Breakdown bars are plain proportional `div`s, no library.

### Consequences

- One dependency (~100 KB gzip with its d3 parts) in the analytics chunk.
- Colours come from the design tokens (CSS variables), so the theme stays one place.
- Upgrading to recharts 3 is a separate change.
