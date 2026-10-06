/**
 * Selling skins to us — the storefront side only. The numbers below are placeholders until
 * the sell API exists (owner, 2026-10-06); they will come from it, not from this file.
 */

/** Our fee on a payout to a card, percent. Placeholder. */
export const SELL_FEE_PERCENT = 5;
/** Extra on a payout to the csmarket balance, percent. Placeholder. */
export const BALANCE_BONUS_PERCENT = 2;
/** The smallest payout to a card, soʻm. Placeholder. */
export const CARD_MIN_UZS = 50_000;

/** Where the money goes. */
export type PayoutMethod = "balance" | "uzcard" | "humo" | "uzum-visa";
export const PAYOUT_METHODS: readonly PayoutMethod[] = ["balance", "uzcard", "humo", "uzum-visa"];

/** The first digits a card of each method starts with. */
const CARD_PREFIX: Readonly<Record<Exclude<PayoutMethod, "balance">, string>> = {
  uzcard: "8600",
  humo: "9860",
  "uzum-visa": "4",
};

/** Why an inventory item cannot be sold. */
export type Unavailable =
  { reason: "tradeLock"; until: string } | { reason: "tooCheap" } | { reason: "notAccepted" };

/** One item of the seller's Steam inventory, as the sell page shows it. */
export interface SellItem {
  /** Steam's asset id: unique in the inventory (two equal skins are two items). */
  assetId: string;
  slug: string;
  name: string;
  /** The catalogue category (`rifles`, `knives`…), for the chips. */
  category: string;
  weapon: string | null;
  skin: string | null;
  exterior: string | null;
  stattrak: boolean;
  imageUrl: string;
  rarityColor: string | null;
  /** What we pay, soʻm. */
  priceUzs: number;
  unavailable: Unavailable | null;
}

export interface SellSummary {
  items: number;
  fee: number;
  bonus: number;
  payout: number;
}

/** The payout for the chosen prices: the balance gets a bonus, a card pays the fee. */
export function sellSummary(prices: readonly number[], method: PayoutMethod): SellSummary {
  const items = prices.reduce((a, b) => a + b, 0);
  const fee = method === "balance" ? 0 : Math.round((items * SELL_FEE_PERCENT) / 100);
  const bonus = method === "balance" ? Math.round((items * BALANCE_BONUS_PERCENT) / 100) : 0;
  return { items, fee, bonus, payout: items - fee + bonus };
}

/** At most 16 digits out of whatever was typed or pasted. */
export function cardDigits(raw: string): string {
  return raw.replace(/\D/g, "").slice(0, 16);
}

/** Digits grouped by four: «8600 1234 5678 9012». */
export function formatCard(digits: string): string {
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ");
}

/** A complete card number that belongs to the method. */
export function cardFits(method: Exclude<PayoutMethod, "balance">, digits: string): boolean {
  return digits.length === 16 && digits.startsWith(CARD_PREFIX[method]);
}
