/** Admin payments API: thin typed wrappers over `/api/v1/admin/payments`. Mirrors the API's schemas. */
import { type PaymentProvider, type PaymentPurpose, type PaymentStatus } from "./kinds";
import { type OrderStatus } from "../orders/kinds";

import { session } from "@/lib/api";

const BASE = "/api/v1/admin/payments";

export interface PaymentUser {
  id: string;
  display_name: string | null;
  avatar_url?: string | null;
}

export interface AdminPaymentRow {
  id: string;
  number: string;
  purpose: PaymentPurpose;
  provider: PaymentProvider;
  /** Whole soʻm as a digit string: the base (the order's price, the top-up's credit). */
  amount_uzs: string;
  /** The kassa fee the buyer paid on top, whole soʻm; `"0"` for none. */
  fee_uzs: string;
  status: PaymentStatus;
  created_at: string;
  succeeded_at: string | null;
  user: PaymentUser;
}

export interface AdminPaymentsPage {
  items: AdminPaymentRow[];
  next_cursor: string | null;
}

export interface PaymentFull extends AdminPaymentRow {
  provider_ref: string | null;
}

export type TopupStatus = "pending" | "succeeded" | "expired" | "reversed" | "held" | "rejected";

export interface PaymentTopup {
  number: string;
  amount_uzs: string;
  status: TopupStatus;
  expires_at: string;
  succeeded_at: string | null;
}

export type KassaProvider = "click" | "payme" | "uzum";

export interface KassaTxn {
  provider: KassaProvider;
  external_id: string;
  status: string;
  /** Digits: soʻm for `soum`, tiyin for `tiyin`. */
  amount: string;
  amount_unit: "soum" | "tiyin";
  times: { created: string | null; performed: string | null; cancelled: string | null };
  /** An allow-list built server-side; the phone, when present, is already masked. */
  extra: Record<string, string>;
}

/** The order a payment pays for. */
export interface PaymentOrder {
  number: string;
  status: OrderStatus;
  /** Whole soʻm as a digit string. */
  price_uzs: string;
}

export interface AdminPaymentDetail {
  payment: PaymentFull;
  topup: PaymentTopup | null;
  order: PaymentOrder | null;
  kassa: KassaTxn[];
}

export interface ListPaymentsParams {
  q?: string;
  status?: PaymentStatus;
  provider?: PaymentProvider;
  purpose?: PaymentPurpose;
  cursor?: string;
}

const PAGE_SIZE = 20;

export function listPayments(p: ListPaymentsParams = {}): Promise<AdminPaymentsPage> {
  const params = new URLSearchParams();
  if (p.q) params.set("q", p.q);
  if (p.status) params.set("status", p.status);
  if (p.provider) params.set("provider", p.provider);
  if (p.purpose) params.set("purpose", p.purpose);
  if (p.cursor) params.set("cursor", p.cursor);
  params.set("limit", String(PAGE_SIZE));
  return session.apiGet<AdminPaymentsPage>(`${BASE}?${params.toString()}`);
}

export function getPayment(id: string): Promise<AdminPaymentDetail> {
  return session.apiGet<AdminPaymentDetail>(`${BASE}/${encodeURIComponent(id)}`);
}

/** «Настройки оплаты»: the percent each kassa adds on top (decimals as strings). */
export type KassaStatus = "on" | "maintenance" | "off";

export interface KassaFees {
  click: string;
  payme: string;
  uzum: string;
  /** A kassa's switch; a missing key is `on` (`off` for `p2p`). */
  statuses: Record<string, KassaStatus>;
}

export interface FeeSettingsOut {
  settings: KassaFees;
  updated_at: string | null;
  updated_by: PaymentUser | null;
}

export function getFeeSettings(): Promise<FeeSettingsOut> {
  return session.apiGet<FeeSettingsOut>(`${BASE}/settings`);
}

/** `version` is the `updated_at` the edit started from (`null`: never saved): a save over
 * someone else's is 409 `settings_stale`. */
export function saveFeeSettings(
  doc: KassaFees,
  version: string | null,
  key: string,
): Promise<FeeSettingsOut> {
  return session.api<FeeSettingsOut>(`${BASE}/settings`, {
    method: "PUT",
    body: doc,
    idempotencyKey: key,
    headers: { "If-Match": version ?? "none" },
  });
}

/** «Лимит без проверки»: what one user may pass through a kassa in a window; over it a payment is held. */
export interface KassaLimit {
  provider: string;
  enabled: boolean;
  max_amount_uzs: string;
  window_hours: number;
}
export interface ReviewLimitsOut {
  limits: KassaLimit[];
  updated_at: string | null;
  updated_by: { id: string; display_name: string | null } | null;
}
export interface KassaLimitIn {
  provider: string;
  enabled: boolean;
  max_amount_uzs: number;
  window_hours: number;
}
export type HoldReason = "kassa_limit" | "user_limit" | "check_failed";
export type HoldDecision = "released" | "returned" | "reversed_by_kassa";
export interface HoldUser {
  id: string;
  display_name: string | null;
}
export interface Hold {
  id: string;
  number: string;
  kind: "topup" | "order";
  provider: string;
  amount_uzs: string;
  reason: HoldReason;
  window_sum_uzs: string | null;
  limit_uzs: string | null;
  user: HoldUser;
  created_at: string;
  decision: HoldDecision | null;
  decided_by: HoldUser | null;
  decided_at: string | null;
}
export interface HoldPage {
  items: Hold[];
  next_cursor: string | null;
}

export const getReviewLimits = (): Promise<ReviewLimitsOut> =>
  session.apiGet<ReviewLimitsOut>(`${BASE}/review-limits`);

/** `version` is the `updated_at` the edit started from; a save over someone else's is 409. */
export function saveReviewLimits(
  limits: KassaLimitIn[],
  version: string | null,
  key: string,
): Promise<ReviewLimitsOut> {
  return session.api<ReviewLimitsOut>(`${BASE}/review-limits`, {
    method: "PUT",
    body: { limits },
    idempotencyKey: key,
    headers: { "If-Match": version ?? "none" },
  });
}

export const getHolds = (state: "open" | "decided", cursor: string | null): Promise<HoldPage> =>
  session.apiGet<HoldPage>(
    `${BASE}/holds?state=${state}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );

export const decideHold = (id: string, act: "release" | "returned", key: string): Promise<Hold> =>
  session.apiPost<Hold>(
    `${BASE}/holds/${encodeURIComponent(id)}/${act}`,
    {},
    { idempotencyKey: key },
  );
