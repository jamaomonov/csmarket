/**
 * The sale page's search and assistant copy, shared by the page (`SellGuide`), its Markdown
 * twin (`/md/sell`) and `/llms.txt`, so all three say the same — and only what the buy-back
 * terms (`legal.sell`) say.
 */

import type { FaqEntry } from "@/lib/skin-seo";

/** The catalogue's `{q, a}` pairs as FAQ entries; anything malformed is dropped. */
export function sellFaq(raw: unknown): FaqEntry[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((e: unknown) => {
    if (typeof e !== "object" || e === null) return [];
    const { q, a } = e as { q?: unknown; a?: unknown }; // a JSON object from the locale file
    return typeof q === "string" && typeof a === "string" ? [{ question: q, answer: a }] : [];
  });
}
