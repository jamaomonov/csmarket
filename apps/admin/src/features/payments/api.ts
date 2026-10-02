/** Admin payments API: thin typed wrappers over `/api/v1/admin/payments`. Mirrors the API's schemas. */
import { type PaymentProvider, type PaymentPurpose, type PaymentStatus } from "./kinds";
import { type OrderStatus } from "../orders/kinds";

import { session } from "@/lib/api";

const BASE = "/api/v1/admin/payments";

export interface PaymentUser {
  id: string;
  display_name: string | null;
}

export interface AdminPaymentRow {
  id: string;
  number: string;
  purpose: PaymentPurpose;
  provider: PaymentProvider;
  /** Whole soʻm as a digit string. */
  amount_uzs: string;
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

export type TopupStatus = "pending" | "succeeded" | "expired" | "reversed";

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
