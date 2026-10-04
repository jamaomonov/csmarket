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
    expect(token("font-sans")).toContain("var(--app-font-sans, ");
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
