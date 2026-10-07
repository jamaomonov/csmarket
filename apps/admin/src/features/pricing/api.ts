/** Admin pricing API: thin typed wrappers over `/api/v1/admin/skins` (M4b). Mirrors the API's schemas. */
import { type AdminSkinItem } from "@/features/catalogue/api";
import { session } from "@/lib/api";

const BASE = "/api/v1/admin/skins";

export interface Bracket {
  from_usd: string;
  percent: string;
}

export interface LiquidityBand {
  min_count: number;
  pp: string;
}

/** The whole pricing document; decimals travel as strings. */
/** Lighter sticker and thin-liquidity markups under a cost bound (ADR-0015). */
export interface CheapTail {
  max_cost_usd: string;
  sticker_pp: string;
  low_liquidity_pp: string;
}

export interface PricingRules {
  expenses_percent: string;
  retail: Bracket[];
  liquidity: LiquidityBand[];
  category_pp: Record<string, string>;
  weapon_pp: Record<string, string>;
  min_margin_usd: string;
  price_floor_usd: string;
  uzs_round_to: number;
  cap_at_steam: boolean;
  /** `null`: no cheap tail. */
  cheap_tail: CheapTail | null;
}

export interface PricingOut {
  rules: PricingRules;
  updated_at: string | null;
  updated_by: { id: string; display_name: string | null } | null;
  items_active: number;
  items_overridden: number;
  rate_uzs: string | null;
}

export interface PreviewIn {
  rules?: PricingRules;
  slug?: string;
  cost_usd?: string;
  category?: string;
  weapon?: string;
  item_pp?: string;
  fixed_price_usd?: string;
}

export type Applied = "formula" | "fixed" | "min_margin" | "steam_cap" | "floor";

export interface PreviewOut {
  price_usd: string;
  price_uzs: string | null;
  cost_usd: string;
  expenses_usd: string;
  bracket_margin_usd: string;
  category_pp: string;
  weapon_pp: string;
  liquidity_pp: string;
  item_pp: string;
  effective_percent: string;
  applied: Applied;
}

export interface ItemPricingIn {
  margin_override_pp: string | null;
  fixed_price_usd: string | null;
}

export interface PricedItem extends AdminSkinItem {
  cost_usd?: string | null;
  margin_override_pp?: string | null;
  fixed_price_usd?: string | null;
}

export function getPricing(): Promise<PricingOut> {
  return session.apiGet<PricingOut>(`${BASE}/pricing`);
}

export function savePricing(rules: PricingRules, key: string): Promise<PricingOut> {
  return session.apiPut<PricingOut>(`${BASE}/pricing`, rules, { idempotencyKey: key });
}

export function previewPrice(body: PreviewIn): Promise<PreviewOut> {
  return session.apiPost<PreviewOut>(`${BASE}/pricing/preview`, body);
}

export function findPricedItems(
  q: string | undefined,
  overridden: boolean,
): Promise<{
  items: PricedItem[];
}> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (overridden) params.set("overridden", "true");
  params.set("limit", "50");
  return session.apiGet(`${BASE}/items?${params.toString()}`);
}

export function saveItemPricing(
  slug: string,
  body: ItemPricingIn,
  key: string,
): Promise<PricedItem> {
  return session.apiPut<PricedItem>(`${BASE}/items/${encodeURIComponent(slug)}/pricing`, body, {
    idempotencyKey: key,
  });
}
