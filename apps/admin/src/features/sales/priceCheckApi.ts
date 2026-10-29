/** «Цена выкупа»: `POST /api/v1/admin/sales/price-check` — writes nothing, so no key. */
import { session } from "@/lib/api";

export type CardKind = "uzcard" | "humo" | "uzum_visa";

export interface CheckedItem {
  name: string;
  image_url: string | null;
  skinslink_usd: string;
  /** `skinslink_usd` at the CBU rate, whole soʻm. */
  skinslink_uzs: string;
  /** Skinslink's raw price before its multipliers (names only). */
  original_usd: string | null;
  /** What we pay for it, soʻm, before the balance bonus or a card fee. */
  price_uzs: string;
  margin_usd: string;
}

export interface PriceCheck {
  items: CheckedItem[];
  /** Names Skinslink does not buy now. */
  missing: string[];
  totals: {
    skinslink_usd: string;
    skinslink_uzs: string;
    items_uzs: string;
    balance_uzs: string;
    card_uzs: Record<CardKind, string>;
    margin_usd: string;
  };
  rate: string;
  /** The plain CBU rate `skinslink_uzs` is at. */
  cbu_rate: string;
}

export type PriceCheckIn = { names: string[] } | { trade_link: string };

export function checkSalePrices(body: PriceCheckIn): Promise<PriceCheck> {
  return session.apiPost<PriceCheck>("/api/v1/admin/sales/price-check", body);
}
