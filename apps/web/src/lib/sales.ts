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
  /** Why a card payout was rejected; set only then. */
  payout_reject_reason: string | null;
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

/** `SalesPage`: newest first; `next_cursor` is `null` on the last page. */
export interface SalesPage {
  items: SaleOut[];
  next_cursor: string | null;
}

export const SALES_KEY = ["sales", "list"] as const;
export const PENDING_KEY = ["sales", "pending"] as const;
export const saleKey = (number: string) => ["sales", "one", number] as const;

/** `GET /sales/{number}`. */
export function getSale(number: string): Promise<SaleOut> {
  return session.apiGet<SaleOut>(`/api/v1/sales/${encodeURIComponent(number)}`);
}

/** `GET /sales?cursor=`. */
export function listSales(cursor?: string): Promise<SalesPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return session.apiGet<SalesPage>(`/api/v1/sales${query}`);
}

/** `GET /sales/pending`: what balance sales will credit once the 7 days pass. */
export function getPendingSales(): Promise<{ pending_uzs: string }> {
  return session.apiGet<{ pending_uzs: string }>("/api/v1/sales/pending");
}

/** How often the sale page asks again: often while the offer is out, rarely while the money
 * waits, never once nothing can change. A socket nudge asks sooner. */
export function salePollInterval(sale: SaleOut | undefined): number | false {
  if (!sale) return false;
  if (sale.status === "creating" || sale.status === "offered") return 5_000;
  if (sale.status === "hold" || (sale.status === "payout" && sale.payout_status === "to_pay")) {
    return 60_000;
  }
  return false;
}
