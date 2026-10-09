/** Admin orders API: thin typed wrappers over `/api/v1/admin/orders`. Mirrors the API's schemas. */
import { type AttentionReason, type FailureReason, type OrderStatus } from "./kinds";

import { type PaymentStatus } from "@/features/payments/kinds";
import { session } from "@/lib/api";

const BASE = "/api/v1/admin/orders";

export interface OrderUser {
  id: string;
  display_name: string | null;
}

export interface AdminOrderRow {
  number: string;
  status: OrderStatus;
  /** The skin's market name (English). */
  name: string;
  phase: string | null;
  /** Whole soʻm as a digit string. */
  price_uzs: string;
  /** `wallet`, a kassa, or `null` until paid. */
  paid_with: string | null;
  user: OrderUser;
  created_at: string;
  /** The trade's open (unresolved) attention only. */
  attention_reason: AttentionReason | null;
  /** Accepted, under Steam's protection until then (Skinslink `hold`); `null` otherwise. */
  protected_until: string | null;
  /** The end is our estimate (LIS-SKINS names none: accepted + 7 days). */
  protected_estimated: boolean;
}

export interface AdminOrdersPage {
  items: AdminOrderRow[];
  next_cursor: string | null;
}

export interface AdminOrderFull {
  number: string;
  status: OrderStatus;
  market_hash_name: string;
  phase: string | null;
  slug: string;
  /** Where the offer is bought. */
  source: "waxpeer" | "skinslink" | "lisskins";
  /** The offer the buyer chose: `wx:<id>` / `sl:<id>`. */
  offer_id: string | null;
  /** The Waxpeer listing; `null` for a Skinslink order. */
  listing_id: number | null;
  cost_units: number;
  /** USD with six places. */
  cost_usd: string;
  price_usd: string;
  price_uzs: string;
  /** USD → UZS rate of the order's snapshot. */
  fx_rate: string;
  /** Percent added to the CBU rate for the soʻm price (ADR-0011). */
  fx_uplift_pct: string;
  margin_usd: string;
  /** Accepted, under Steam's protection until then (Skinslink `hold`); `null` otherwise. */
  protected_until: string | null;
  /** The end is our estimate (LIS-SKINS names none: accepted + 7 days). */
  protected_estimated: boolean;
  /** Already masked by the API: the token is never in the page. */
  trade_link_masked: string | null;
  paid_with: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string;
  paid_at: string | null;
  /** When a worker took the order to buy. */
  claimed_at: string | null;
  /** When the Steam offer went out. */
  trade_sent_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
  failed_at: string | null;
  refunded_at: string | null;
  refunded_to: "balance" | null;
  failure_reason: FailureReason | null;
}

export interface AdminTradeOut {
  /** Our id at Waxpeer (= the order id). */
  project_id: string;
  waxpeer_id: number | null;
  paid_units: number;
  bought_units: number | null;
  status: number | null;
  escrow_status: string | null;
  trade_id: string | null;
  offer_url: string | null;
  send_until: string | null;
  release_date: string | null;
  accepted_at: string | null;
  is_released: boolean;
  reason: string | null;
  /** Waxpeer's penalties object as received; any shape. */
  penalties: unknown;
  /** The seller's public fields as stored (scalars). */
  seller: Record<string, unknown>;
  buy_pending: boolean;
  attention_reason: AttentionReason | null;
  resolved_at: string | null;
  resolved_note: string | null;
}

export interface AdminOrderPayment {
  id: string;
  provider: string;
  status: PaymentStatus;
  amount_uzs: string;
  created_at: string;
}

/** A Skinslink order's purchase (spec 2026-10-06). */
export interface AdminSkinslinkPurchaseOut {
  /** Our idempotency key at Skinslink — what their dashboard is searched by. */
  merchant_tx_id: string;
  asset_id: string;
  purchase_id: number | null;
  status: string | null;
  offer_id: string | null;
  offer_url: string | null;
  fail_reason: string | null;
  /** USD with six places. */
  amount_usd: string | null;
  hold_end_date: string | null;
  buy_pending: boolean;
  buy_unconfirmed_at: string | null;
  attention_reason: AttentionReason | null;
  resolved_at: string | null;
}

/** A LIS-SKINS order's purchase (spec 2026-10-07). */
export interface AdminLisskinsPurchaseOut {
  /** Our idempotency key at LIS-SKINS — what its purchase history is searched by. */
  custom_id: string;
  skin_id: number;
  purchase_id: number | null;
  status: string | null;
  return_reason: string | null;
  error: string | null;
  offer_id: string | null;
  offer_url: string | null;
  offer_expiry_at: string | null;
  /** USD with six places. */
  amount_usd: string | null;
  buy_pending: boolean;
  buy_unconfirmed_at: string | null;
  attention_reason: AttentionReason | null;
  resolved_at: string | null;
}

export interface AdminOrderDetail {
  order: AdminOrderFull;
  user: OrderUser;
  trade: AdminTradeOut | null;
  /** `null` for a Waxpeer order. */
  skinslink: AdminSkinslinkPurchaseOut | null;
  /** `null` unless a LIS-SKINS order. */
  lisskins: AdminLisskinsPurchaseOut | null;
  payments: AdminOrderPayment[];
  can_refund: boolean;
  can_retry: boolean;
}

export interface ListOrdersParams {
  q?: string;
  status?: OrderStatus;
  user_id?: string;
  cursor?: string;
}

const PAGE_SIZE = 20;

export function listOrders(p: ListOrdersParams = {}): Promise<AdminOrdersPage> {
  const params = new URLSearchParams();
  if (p.q) params.set("q", p.q);
  if (p.status) params.set("status", p.status);
  if (p.user_id) params.set("user_id", p.user_id);
  if (p.cursor) params.set("cursor", p.cursor);
  params.set("limit", String(PAGE_SIZE));
  return session.apiGet<AdminOrdersPage>(`${BASE}?${params.toString()}`);
}

export function getOrder(number: string): Promise<AdminOrderDetail> {
  return session.apiGet<AdminOrderDetail>(`${BASE}/${encodeURIComponent(number)}`);
}

/** Mark the trade's attention as handled. `key` is one per confirmed submission. */
export function resolveOrder(
  number: string,
  note: string | null,
  key: string,
): Promise<AdminOrderDetail> {
  return session.apiPost<AdminOrderDetail>(
    `${BASE}/${encodeURIComponent(number)}/resolve`,
    { note },
    { idempotencyKey: key },
  );
}

/** Credit the price back to the buyer's balance. */
export function refundOrder(number: string, key: string): Promise<AdminOrderDetail> {
  return session.apiPost<AdminOrderDetail>(
    `${BASE}/${encodeURIComponent(number)}/refund`,
    undefined,
    { idempotencyKey: key },
  );
}

/** Let the worker try the buy again (it looks the purchase up at Waxpeer first). */
export function retryOrder(number: string, key: string): Promise<AdminOrderDetail> {
  return session.apiPost<AdminOrderDetail>(
    `${BASE}/${encodeURIComponent(number)}/retry`,
    undefined,
    { idempotencyKey: key },
  );
}
