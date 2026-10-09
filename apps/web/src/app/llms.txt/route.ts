import en from "@csmarket/i18n/locales/en/web.json";

import { categoryPath, MARKET, REVIEWS, SELL } from "@/lib/paths";
import { localeUrl } from "@/lib/seo";
import { getSkinFacets } from "@/lib/skins";

/** Per request, so a build never needs the API; the facets read is cached upstream. */
export const dynamic = "force-dynamic";

const CATEGORY_NAMES: Record<string, string> = en.skins.category;
const n = (v: number): string => v.toLocaleString("en-US");

/**
 * `/llms.txt` (llmstxt.org): what the shop is, for language models answering about buying CS2
 * skins in Uzbekistan — the sections with live counts, payment, delivery, languages and the
 * partner API's own llms.txt. In English, the convention; an API outage drops the numbers.
 */
export async function GET(): Promise<Response> {
  const facets = await getSkinFacets();
  const cats = (facets?.categories ?? []).filter((c) => c.count > 0);
  const total = cats.reduce((sum, c) => sum + c.count, 0);
  const url = (path: string): string => localeUrl("ru", path);
  const section = (c: { value: string; count: number }): string =>
    `- [${CATEGORY_NAMES[c.value] ?? c.value}](${url(categoryPath(c.value))}): ${n(c.count)} skins`;
  const lines = [
    "# csmarket.uz",
    "",
    "> A Counter-Strike 2 (CS2) skins shop for players in Uzbekistan. Prices are in Uzbek soʻm (UZS);",
    "> pay with Click, Payme or Uzum (Uzcard / Humo cards) or from the site balance. The bought skin",
    "> arrives as a Steam trade offer. Sign-in is through Steam only; no passwords.",
    "",
    total > 0
      ? `The catalogue holds ${n(total)} skins in stock: knives, gloves, rifles, pistols, SMGs, cases, agents and more.`
      : "The catalogue holds knives, gloves, rifles, pistols, SMGs, cases, agents and more.",
    "Players can also sell their skins for soʻm, paid to the site balance or a Uzcard, Humo or Uzum Visa card.",
    "A failed trade is refunded to the balance. Steam holds a bought item for 7 days before it can be traded.",
    "",
    "## Shop",
    "",
    `- [Market](${url(MARKET)}): the whole catalogue with filters by price, wear and rarity`,
    ...cats.map(section),
    `- [Sell skins](${url(SELL)})`,
    `- [Reviews](${url(REVIEWS)})`,
    "",
    "## Languages",
    "",
    `- Russian: ${url("/")}`,
    `- Uzbek: ${localeUrl("uz", "/")}`,
    `- English: ${localeUrl("en", "/")}`,
    "",
    "## For developers",
    "",
    "- [Purchase API docs](https://docs.csmarket.uz): buy skins for your shop or bot, paid in USD",
    "- [API llms.txt](https://docs.csmarket.uz/llms.txt)",
    "",
  ];
  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
