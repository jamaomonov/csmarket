/**
 * Selling skins to us: wire shapes and calls for `/api/v1/sell*`, and the cart's arithmetic.
 *
 * The API decides every number. The cart computes the payout the same way — each soʻm figure
 * rounded down to 100, percents to two places — only to show it before the click, and sends
 * it as `expected_payout_uzs`: another server figure is 409 `prices_changed`. A card number is
 * typed here and sent once, with the sale; it is never logged or stored in the browser.
 */
import { SessionApiError } from "@csmarket/api-client";
import { assertNever } from "@csmarket/utils";

import { session } from "./api";

import type { SaleOut } from "./sales";

export type CardType = "uzcard" | "humo" | "uzum_visa";
export const CARD_TYPES: readonly CardType[] = ["uzcard", "humo", "uzum_visa"];

/** `SellConfigOut`: public, read by the page before anything is chosen. */
export interface SellConfig {
  enabled: boolean;
  balance_bonus_pct: string;
  card_fee_pct: Record<CardType, string>;
  card_min_uzs: string;
  /** The minimum sum in soʻm, a hint (the API decides); `null` without a rate. */
  min_sum_uzs: string | null;
  max_cards: number;
}

/** `SellItemOut`: an item we buy now, at our price. */
export interface SellItem {
  asset_id: string;
  /** Steam's market name; skin names stay English. */
  name: string;
  image_url: string | null;
  exterior: string | null;
  rarity_color: string | null;
  /** Our catalogue's category, for the chips; `null` when we do not list the item. */
  category: string | null;
  price_uzs: string;
}

/** `InventoryOut`. */
export interface Inventory {
  items: SellItem[];
  max_items: number;
  min_sum_uzs: string;
  fetched_at: string;
}

/** Where the money goes: the balance, a saved card, or a card typed in the cart. */
export type Payout =
  | { to: "balance" }
  | { to: "saved"; cardId: string; type: CardType }
  | { to: "new"; type: CardType; digits: string };

export interface SellSummary {
  items: number;
  bonus: number;
  fee: number;
  payout: number;
}

const floor100 = (n: number): number => Math.floor(n / 100) * 100;
/** A percent with up to two decimals in hundredths of a percent («1.5» → 150), so the
 * arithmetic stays on integers as the API's `Decimal` does. */
const basisPoints = (pct: string): number => Math.round(Number(pct) * 100);

/** The payout's card type; `null` for the balance. */
export function payoutCardType(p: Payout): CardType | null {
  return p.to === "balance" ? null : p.type;
}

/** The cart's money: the balance gets the bonus, a card pays its type's fee. */
export function sellSummary(
  prices: readonly number[],
  payout: Payout,
  config: SellConfig,
): SellSummary {
  const items = prices.reduce((a, b) => a + b, 0);
  const type = payoutCardType(payout);
  if (type === null) {
    const total = floor100((items * (10_000 + basisPoints(config.balance_bonus_pct))) / 10_000);
    return { items, bonus: total - items, fee: 0, payout: total };
  }
  const total = floor100((items * (10_000 - basisPoints(config.card_fee_pct[type]))) / 10_000);
  return { items, bonus: 0, fee: items - total, payout: total };
}

/** At most 16 digits out of whatever was typed or pasted. */
export function cardDigits(raw: string): string {
  return raw.replace(/\D/g, "").slice(0, 16);
}

/** Digits grouped by four: «9860 1234 5678 9015». */
export function formatCard(digits: string): string {
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ");
}

/** The first digits of each card type we pay to (Uzcard has two ranges). */
export const CARD_PREFIX: Readonly<Record<CardType, readonly string[]>> = {
  uzcard: ["8600", "5614"],
  humo: ["9860"],
  uzum_visa: ["4"],
};

/** Whether `digits` start with one of `type`'s prefixes. */
export function hasPrefix(type: CardType, digits: string): boolean {
  return CARD_PREFIX[type].some((p) => digits.startsWith(p));
}

/** The Luhn check: every second digit from the right doubled. */
export function luhnOk(digits: string): boolean {
  let total = 0;
  for (let i = 0; i < digits.length; i++) {
    const d = Number(digits.charAt(digits.length - 1 - i));
    total += i % 2 === 1 ? (d * 2 > 9 ? d * 2 - 9 : d * 2) : d;
  }
  return total % 10 === 0;
}

/** A complete number of `type` that passes Luhn. */
export function cardFits(type: CardType, digits: string): boolean {
  return digits.length === 16 && hasPrefix(type, digits) && luhnOk(digits);
}

/** «StatTrak™ AK-47 | Redline (Field-Tested)» → AK-47, Redline, StatTrak. */
export function nameParts(name: string): {
  weapon: string | null;
  skin: string;
  stattrak: boolean;
} {
  const stattrak = name.includes("StatTrak™");
  const bare = name
    .replace(/^★\s*/, "")
    .replace("StatTrak™ ", "")
    .replace(/\s*\([^)]*\)\s*$/, "");
  const [weapon, skin] = bare.split(" | ");
  return skin === undefined
    ? { weapon: null, skin: bare, stattrak }
    : { weapon: weapon ?? null, skin, stattrak };
}

export const INVENTORY_KEY = ["sell", "inventory"] as const;

/** `GET /sell/inventory`; `refresh` asks Skinslink again instead of the kept copy. */
export function getInventory(refresh = false): Promise<Inventory> {
  return session.apiGet<Inventory>(`/api/v1/sell/inventory${refresh ? "?refresh=1" : ""}`);
}

/** `SellIn`. */
export interface SellBody {
  asset_ids: string[];
  payout:
    | { to: "balance" }
    | { to: "card"; card_id: string }
    | { to: "card"; new_card: { type: CardType; number: string } };
  /** Whole soʻm the cart showed, a JSON integer. */
  expected_payout_uzs: number;
}

/** The request body for the chosen items and payout. */
export function sellBody(assetIds: readonly string[], payout: Payout, expected: number): SellBody {
  const base = { asset_ids: [...assetIds], expected_payout_uzs: expected };
  switch (payout.to) {
    case "balance":
      return { ...base, payout: { to: "balance" } };
    case "saved":
      return { ...base, payout: { to: "card", card_id: payout.cardId } };
    case "new":
      return {
        ...base,
        payout: { to: "card", new_card: { type: payout.type, number: payout.digits } },
      };
    default:
      return assertNever(payout);
  }
}

/** A fresh `POST /sell` key (16–160 chars on the API side): one per cart sent. */
export function mintSellKey(): string {
  return `web-sell-${crypto.randomUUID()}`;
}

export type SellErrorCode =
  | "prices_changed"
  | "below_minimum"
  | "below_card_minimum"
  | "too_many_items"
  | "steam_refused"
  | "sales_disabled"
  | "cards_limit"
  | "card_invalid"
  | "trade_link_missing"
  | "trade_link_bad"
  | "rate_unavailable"
  | "sales_unavailable";

const SELL_ERRORS: ReadonlySet<string> = new Set<SellErrorCode>([
  "prices_changed",
  "below_minimum",
  "below_card_minimum",
  "too_many_items",
  "steam_refused",
  "sales_disabled",
  "cards_limit",
  "card_invalid",
  "trade_link_missing",
  "trade_link_bad",
  "rate_unavailable",
  "sales_unavailable",
]);

/** A refusal the sell page explains; `reason` is the Steam account code of `steam_refused`. */
export class SellError extends Error {
  constructor(
    public readonly code: SellErrorCode,
    public readonly reason: string | null,
  ) {
    super(code);
    this.name = "SellError";
  }
}

/** The API's 409 / 422 / 503 of the sell routes as a {@link SellError}; anything else `null`. */
export function sellError(err: unknown): SellError | null {
  if (err instanceof SellError) return err;
  if (!(err instanceof SessionApiError)) return null;
  const code = err.code ?? "";
  if (!SELL_ERRORS.has(code)) return null;
  // A problem+json body: an unknown JSON object, of which only the `reason` field is read.
  const body =
    typeof err.body === "object" && err.body !== null ? (err.body as Record<string, unknown>) : {};
  // Narrowed by the set above.
  return new SellError(code as SellErrorCode, typeof body.reason === "string" ? body.reason : null);
}

/** `POST /sell`; a refusal comes back as a {@link SellError}. */
export async function createSale(body: SellBody, key: string): Promise<SaleOut> {
  try {
    return await session.apiPost<SaleOut>("/api/v1/sell", body, { idempotencyKey: key });
  } catch (err) {
    throw sellError(err) ?? err;
  }
}
