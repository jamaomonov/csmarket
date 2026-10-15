import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * The type scale from `tokens.css` (`--text-meta` … `--text-h1`). tailwind-merge does not
 * read the theme, so without this it takes `text-small` for a colour and drops it beside
 * `text-fg-muted`.
 */
const TYPE_SCALE = ["meta", "label", "small", "body", "lead", "title", "h3", "h2", "h1"];

const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: TYPE_SCALE }] } },
});

/**
 * Merge Tailwind class names while resolving conflicts deterministically.
 * Prefer this over raw `clsx` so duplicate utilities collapse.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
