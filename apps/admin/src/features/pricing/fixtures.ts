/** Test fixtures for the pricing page (a pricing document as the API answers it). */
import { type PricingOut, type PreviewOut } from "./api";

export const PRICING: PricingOut = {
  rules: {
    expenses_percent: "3",
    retail: [
      { from_usd: "0", percent: "10" },
      { from_usd: "1", percent: "5" },
    ],
    liquidity: [
      { min_count: 4, pp: "0" },
      { min_count: 0, pp: "3" },
    ],
    category_pp: { stickers: "5" },
    weapon_pp: {},
    min_margin_usd: "0.02",
    price_floor_usd: "0.10",
    uzs_round_to: 100,
    cap_at_steam: false,
    cheap_tail: { max_cost_usd: "1", sticker_pp: "2", low_liquidity_pp: "1" },
  },
  updated_at: "2026-10-02T09:00:00Z",
  updated_by: { id: "u-admin", display_name: "Жамшид" },
  items_active: 21000,
  items_overridden: 4,
  rate_uzs: "12700.0000",
};

export const QUOTE: PreviewOut = {
  price_usd: "11.55",
  price_uzs: "146700",
  cost_usd: "10",
  expenses_usd: "0.3",
  bracket_margin_usd: "0.55",
  category_pp: "0",
  weapon_pp: "0",
  liquidity_pp: "0",
  item_pp: "0",
  effective_percent: "15.5",
  applied: "formula",
};
