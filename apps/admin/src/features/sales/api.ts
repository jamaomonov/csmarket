/**
 * Admin «Выкуп» API: thin typed wrappers over `/api/v1/admin/sales` (sales, settings, sell
 * blocks). The payout requests are in `payoutsApi.ts`. Mirrors the API's schemas.
 */
import { type PayoutRow } from "./payoutsApi";

import { session } from "@/lib/api";

const BASE = "/api/v1/admin/sales";

export type CardType = "uzcard" | "humo" | "uzum_visa";
export type SaleStatus =
  "creating" | "offered" | "hold" | "credited" | "payout" | "closed" | "reverted";

/** The card types in the order the settings form lists them. */
export const CARD_TYPES_ORDER: readonly CardType[] = ["uzcard", "humo", "uzum_visa"];

export const SALE_STATUSES: readonly SaleStatus[] = [
  "creating",
  "offered",
  "hold",
  "credited",
  "payout",
  "closed",
  "reverted",
];

export type AttentionReason = "rolled_back" | "late_deposit" | "credit_blocked";
export type AttentionFilter = "open" | "resolved" | "any";
export const ATTENTION_FILTERS: readonly AttentionFilter[] = ["open", "resolved", "any"];

export interface AdminUser {
  id: string;
  display_name: string | null;
  avatar_url?: string | null;
}

export interface AdminSaleItem {
  asset_id: string;
  name: string;
  image_url?: string | null;
  price_usd: string;
  price_uzs: string;
}

export interface AdminSaleRow {
  number: string;
  status: SaleStatus;
  user: AdminUser;
  payout_to: "balance" | "card";
  quoted_usd: string;
  payout_uzs: string;
  margin_usd: string;
  attention_reason: AttentionReason | null;
  /** Set and not marked «Проверено» yet. */
  attention_open: boolean;
  created_at: string;
  /** The dearest skin of the sale (the list rows carry it). */
  first_item?: { name: string; image_url: string | null } | null;
  /** How many skins the sale has (the list rows carry it). */
  items_count?: number;
}

/** A sale on the user page, with the skins it sold. */
export interface AdminUserSale extends AdminSaleRow {
  items: { name: string; image_url: string | null }[];
}

/** The user page's «Продажи»: the totals of what reached us and the latest 20. */
export interface AdminUserSales {
  sold_count: number;
  sold_uzs: string;
  items: AdminUserSale[];
}

export interface AdminSalesPage {
  items: AdminSaleRow[];
  next_cursor: string | null;
  /** Every sale with an open attention, whatever the filters. */
  attention_open: number;
}

export interface AdminSale {
  number: string;
  status: SaleStatus;
  user: AdminUser;
  payout_to: "balance" | "card";
  card_type: CardType | null;
  card_masked: string | null;
  quoted_usd: string;
  amount_usd: string | null;
  items_uzs: string;
  bonus_uzs: string;
  fee_uzs: string;
  payout_uzs: string;
  rate: string;
  margin_usd: string;
  trade_id: number | null;
  trade_offer_id: string | null;
  bot_name: string | null;
  offer_expiry_at: string | null;
  hold_end_at: string | null;
  fail_reason: string | null;
  attention_reason: AttentionReason | null;
  attention_open: boolean;
  resolved_at: string | null;
  resolved_by: AdminUser | null;
  resolved_note: string | null;
  credited_at: string | null;
  created_at: string;
  updated_at: string;
  items: AdminSaleItem[];
  payout: PayoutRow | null;
}

export interface Bracket {
  from_usd: string;
  percent: string;
}

/** The sale-settings document; decimals travel as strings. */
export interface SaleSettings {
  enabled: boolean;
  margin: Bracket[];
  rate_cut_pct: string;
  balance_bonus_pct: string;
  card_fee_pct: Record<CardType, string>;
  card_min_uzs: number;
  min_sum_usd: string;
  /** What the bank charges us on a card transfer, percent; optional for an older API. */
  bank_fee_pct?: string;
  /** USD ceilings; `null` = no limit. */
  max_sale_usd?: string | null;
  max_user_day_usd?: string | null;
  max_day_usd?: string | null;
}

export type SettingsWarning = "balance_bonus_eats_margin";

export interface SaleSettingsOut {
  settings: SaleSettings;
  updated_at: string | null;
  updated_by: AdminUser | null;
  rate_uzs: string | null;
  warnings?: SettingsWarning[];
}

export interface SellBlock {
  user: AdminUser;
  blocked: boolean;
  reason: string | null;
  blocked_by: AdminUser | null;
  blocked_at: string | null;
}

export interface ListSalesParams {
  status?: SaleStatus;
  q?: string;
  cursor?: string;
  attention?: AttentionFilter;
}

export function listSales(p: ListSalesParams): Promise<AdminSalesPage> {
  const params = new URLSearchParams();
  if (p.status) params.set("status", p.status);
  if (p.q) params.set("q", p.q);
  if (p.attention) params.set("attention", p.attention);
  if (p.cursor) params.set("cursor", p.cursor);
  return session.apiGet<AdminSalesPage>(`${BASE}?${params.toString()}`);
}

export function getUserSales(userId: string): Promise<AdminUserSales> {
  return session.apiGet<AdminUserSales>(`${BASE}/users/${encodeURIComponent(userId)}`);
}

export function getSale(number: string): Promise<AdminSale> {
  return session.apiGet<AdminSale>(`${BASE}/${encodeURIComponent(number)}`);
}

export function getSaleSettings(): Promise<SaleSettingsOut> {
  return session.apiGet<SaleSettingsOut>(`${BASE}/settings`);
}

/** `version` is the `updated_at` the edit started from (`null`: never saved): a save over
 * someone else's is 409 `settings_stale`. */
export function saveSaleSettings(
  doc: SaleSettings,
  version: string | null,
  key: string,
): Promise<SaleSettingsOut> {
  return session.api<SaleSettingsOut>(`${BASE}/settings`, {
    method: "PUT",
    body: doc,
    idempotencyKey: key,
    headers: { "If-Match": version ?? "none" },
  });
}

/** «Проверено»: the sale's attention is handled. */
export function resolveSale(number: string, note: string | null, key: string): Promise<AdminSale> {
  return session.apiPost<AdminSale>(
    `${BASE}/${encodeURIComponent(number)}/resolve`,
    { note },
    { idempotencyKey: key },
  );
}

export function listSellBlocks(): Promise<{ items: SellBlock[] }> {
  return session.apiGet<{ items: SellBlock[] }>(`${BASE}/blocks`);
}

export function getSellBlock(userId: string): Promise<SellBlock> {
  return session.apiGet<SellBlock>(`${BASE}/blocks/${encodeURIComponent(userId)}`);
}

/** Block (a reason is required) or unblock a user's selling. */
export function setSellBlock(
  userId: string,
  blocked: boolean,
  reason: string | null,
  key: string,
): Promise<SellBlock> {
  return session.apiPut<SellBlock>(
    `${BASE}/blocks/${encodeURIComponent(userId)}`,
    { blocked, reason },
    { idempotencyKey: key },
  );
}
