/**
 * A seller's sales and saved cards: wire shapes and calls for `/api/v1/sales*` and
 * `/api/v1/payout-cards`. A card is shown by its type and last four digits only.
 */
import { session } from "./api";

import type { CardType } from "./sell";

export type SaleStatus =
  "creating" | "offered" | "hold" | "credited" | "payout" | "closed" | "reverted";

export type PayoutStatus = "waiting_hold" | "to_pay" | "paid" | "rejected" | "canceled";

/** `SaleOut`. Money in whole soʻm, as strings. */
export interface SaleOut {
  number: string;
  status: SaleStatus;
  payout_to: "balance" | "card";
  card: { type: CardType; last4: string } | null;
  items_uzs: string;
  bonus_uzs: string;
  fee_uzs: string;
  payout_uzs: string;
  items: { asset_id: string; name: string; image_url: string | null; price_uzs: string }[];
  /** The Steam offer to accept, while `offered`. */
  offer: { url: string; bot_name: string | null; expires_at: string | null } | null;
  /** When the money is due, while `hold`. */
  money_at: string | null;
  payout_status: PayoutStatus | null;
  created_at: string;
}

/** `CardOut`. */
export interface SavedCard {
  id: string;
  type: CardType;
  last4: string;
  created_at: string;
}

export const CARDS_KEY = ["payout-cards"] as const;

/** `GET /payout-cards`. */
export function listCards(): Promise<{ items: SavedCard[] }> {
  return session.apiGet<{ items: SavedCard[] }>("/api/v1/payout-cards");
}

/** `DELETE /payout-cards/{id}` (204). */
export function deleteCard(id: string, key: string): Promise<undefined> {
  return session.api<undefined>(`/api/v1/payout-cards/${encodeURIComponent(id)}`, {
    method: "DELETE",
    idempotencyKey: key,
  });
}

/** A fresh `DELETE /payout-cards/{id}` key. */
export function mintCardKey(): string {
  return `web-card-${crypto.randomUUID()}`;
}
