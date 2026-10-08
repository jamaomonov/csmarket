/** Admin «Выкуп» API: thin typed wrappers over `/api/v1/admin/sales`. Mirrors the API's schemas. */
import { session } from "@/lib/api";

const BASE = "/api/v1/admin/sales";

export type CardType = "uzcard" | "humo" | "uzum_visa";
export type SaleStatus =
  "creating" | "offered" | "hold" | "credited" | "payout" | "closed" | "reverted";
export type PayoutStatus = "to_pay" | "waiting_hold" | "paid" | "rejected" | "canceled";

/** The card types in the order the settings form lists them. */
export const CARD_TYPES_ORDER: readonly CardType[] = ["uzcard", "humo", "uzum_visa"];

/** The tabs, in the order the queue shows them; «К выплате» first. */
export const PAYOUT_STATUSES: readonly PayoutStatus[] = [
  "to_pay",
  "waiting_hold",
  "paid",
  "rejected",
  "canceled",
];
export const SALE_STATUSES: readonly SaleStatus[] = [
  "creating",
  "offered",
  "hold",
  "credited",
  "payout",
  "closed",
  "reverted",
];

export interface AdminUser {
  id: string;
  display_name: string | null;
}

export interface PayoutRow {
  id: string;
  sale_number: string;
  user: AdminUser;
  card_type: CardType;
  /** `•••• 9015` — never the number. */
  card_masked: string;
  amount_uzs: string;
  fee_uzs: string;
  status: PayoutStatus;
  to_pay_at: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface PayoutsPage {
  items: PayoutRow[];
  counts: Record<PayoutStatus, number>;
  next_cursor: string | null;
}

export interface AdminSaleItem {
  asset_id: string;
  name: string;
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
  attention_reason: string | null;
  created_at: string;
}

export interface AdminSalesPage {
  items: AdminSaleRow[];
  next_cursor: string | null;
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
  attention_reason: string | null;
  credited_at: string | null;
  created_at: string;
  updated_at: string;
  items: AdminSaleItem[];
  payout: PayoutRow | null;
}

export interface PayoutDetail {
  request: PayoutRow;
  note: string | null;
  reject_reason: string | null;
  decided_by: AdminUser | null;
  sale: AdminSale;
  history_sales: AdminSaleRow[];
  history_payouts: PayoutRow[];
  can_decide: boolean;
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
}

export interface SaleSettingsOut {
  settings: SaleSettings;
  updated_at: string | null;
  updated_by: AdminUser | null;
  rate_uzs: string | null;
}

export function listPayouts(status: PayoutStatus, cursor?: string): Promise<PayoutsPage> {
  const params = new URLSearchParams({ status });
  if (cursor) params.set("cursor", cursor);
  return session.apiGet<PayoutsPage>(`${BASE}/payouts?${params.toString()}`);
}

export function getPayout(id: string): Promise<PayoutDetail> {
  return session.apiGet<PayoutDetail>(`${BASE}/payouts/${encodeURIComponent(id)}`);
}

/** The full card number (audited on the API side). Never keep it beyond the page. */
export function revealCard(id: string, purpose: "show" | "copy"): Promise<{ number: string }> {
  return session.apiPost<{ number: string }>(`${BASE}/payouts/${encodeURIComponent(id)}/reveal`, {
    purpose,
  });
}

export function markPaid(id: string, note: string | null, key: string): Promise<PayoutDetail> {
  return session.apiPost<PayoutDetail>(
    `${BASE}/payouts/${encodeURIComponent(id)}/paid`,
    { note },
    { idempotencyKey: key },
  );
}

export function rejectPayout(id: string, reason: string, key: string): Promise<PayoutDetail> {
  return session.apiPost<PayoutDetail>(
    `${BASE}/payouts/${encodeURIComponent(id)}/reject`,
    { reason },
    { idempotencyKey: key },
  );
}

export interface ListSalesParams {
  status?: SaleStatus;
  q?: string;
  cursor?: string;
}

export function listSales(p: ListSalesParams): Promise<AdminSalesPage> {
  const params = new URLSearchParams();
  if (p.status) params.set("status", p.status);
  if (p.q) params.set("q", p.q);
  if (p.cursor) params.set("cursor", p.cursor);
  return session.apiGet<AdminSalesPage>(`${BASE}?${params.toString()}`);
}

export function getSale(number: string): Promise<AdminSale> {
  return session.apiGet<AdminSale>(`${BASE}/${encodeURIComponent(number)}`);
}

export function getSaleSettings(): Promise<SaleSettingsOut> {
  return session.apiGet<SaleSettingsOut>(`${BASE}/settings`);
}

export function saveSaleSettings(doc: SaleSettings, key: string): Promise<SaleSettingsOut> {
  return session.apiPut<SaleSettingsOut>(`${BASE}/settings`, doc, { idempotencyKey: key });
}
