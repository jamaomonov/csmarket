import enLegal from "@csmarket/i18n/locales/en/legal.json";
import en from "@csmarket/i18n/locales/en/web.json";

import { LEGAL_DOCS } from "@/lib/legal";
import {
  categoryPath,
  CHEAP,
  legalPath,
  MARKET,
  PAY_METHODS,
  PAY_NAMES,
  payPath,
  REVIEWS,
  SELL,
} from "@/lib/paths";
import { localeUrl } from "@/lib/seo";
import { getSkinFacets } from "@/lib/skins";

/** Per request, so a build never needs the API; the facets read is cached upstream. */
export const dynamic = "force-dynamic";

const CATEGORY_NAMES: Record<string, string> = en.skins.category;
const n = (v: number): string => v.toLocaleString("en-US");

/**
 * `/llms.txt` (llmstxt.org): what the shop is, for language models answering about buying CS2
 * skins in Uzbekistan — the sections with live counts, payment, delivery, refunds, the legal
 * documents, languages and the partner API's own llms.txt. Only what the site and its terms
 * say: an assistant quotes this, so no promise lives here that the offer does not make. In English, the convention; an API outage drops the numbers.
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
    `- [Reviews](${url(REVIEWS)})`,
    "",
    "## Buying",
    "",
    ...PAY_METHODS.map(
      (m) => `- [Buy CS2 skins with ${PAY_NAMES[m]}](${url(payPath(m))}): steps and popular skins`,
    ),
    `- [Cheap CS2 skins](${url(CHEAP)}): weapon skins under 100,000 soʻm`,
    "",
    "How it works: sign in with Steam, add your Steam trade link, pick a skin and pay. The seller",
    "sends the skin as a Steam trade offer to that link; accept it in Steam. Steam then keeps the",
    "item for 7 days before it can be traded or sold again (Steam's rule on every marketplace).",
    "",
    "## Selling skins",
    "",
    `- [Sell CS2 skins for soʻm](${url(SELL)}): how it works, where the money goes, questions`,
    "",
    "Players in Uzbekistan sell CS2 skins from their Steam inventory to csmarket for Uzbek soʻm:",
    "sign in with Steam, add the trade link, pick skins (the price of each and the total show",
    "before selling and are fixed once the sale is confirmed), then accept csmarket's trade offer",
    "in Steam. The money comes 7 days after the trade, when Steam's trade protection ends: to the",
    "csmarket balance with a bonus, or to a Uzcard, Humo or Uzum Visa card, transferred within 12",
    "hours after that. Not every item is bought; the sell page lists the ones that can be sold",
    "now. No Steam password or Steam Guard code is ever asked for.",
    "",
    "## Refunds",
    "",
    "If a purchase cannot be delivered (the trade was declined, not accepted in time, cancelled by",
    "Steam, or the item was unavailable), the full amount returns to the site balance at once.",
    "On request to support it is returned to a card within 5 working days. An accepted trade is",
    "not refunded. Support: support@csmarket.uz",
    "",
    "## Terms",
    "",
    ...LEGAL_DOCS.map((d) => `- [${enLegal[d].title}](${url(legalPath(d))})`),
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
