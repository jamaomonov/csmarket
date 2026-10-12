/** Admin «Заявки на выплату» API: `/api/v1/admin/sales/payouts`. Mirrors the API's schemas. */
import { type AdminSale, type AdminSaleRow, type AdminUser, type CardType } from "./api";

import { session } from "@/lib/api";

const BASE = "/api/v1/admin/sales/payouts";

export type PayoutStatus = "to_pay" | "waiting_hold" | "paid" | "rejected" | "canceled";
/** A tab of the queue; `all` is the search across every status. */
export type PayoutTab = PayoutStatus | "all";
export type PayoutFlag =
  "banned" | "wallet_frozen" | "sell_blocked" | "new_account" | "shared_card" | "rolled_back";

/** The tabs, in the order the queue shows them; «К выплате» first. */
export const PAYOUT_STATUSES: readonly PayoutStatus[] = [
  "to_pay",
  "waiting_hold",
  "paid",
  "rejected",
  "canceled",
];

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
  /** «Беру в работу»: who pays it now and until when; `null` when free. */
  claimed_by?: AdminUser | null;
  claimed_until?: string | null;
  flags?: PayoutFlag[];
}

export interface PayoutTotals {
  to_pay_count: number;
  to_pay_uzs: string;
  paid_today_count: number;
  paid_today_uzs: string;
  rejected_today_count: number;
}

export interface PayoutsPage {
  items: PayoutRow[];
  counts: Record<PayoutStatus, number>;
  totals?: PayoutTotals;
  next_cursor: string | null;
}

export interface PayoutRisk {
  steam_url: string | null;
  account_created_at: string | null;
  banned: boolean;
  ban_reason: string | null;
  wallet_frozen: boolean;
  sell_blocked: boolean;
  sell_block_reason: string | null;
  sold_count: number;
  sold_uzs: string;
  paid_count: number;
  paid_uzs: string;
  card_paid_uzs: string;
  day_count: number;
  day_usd: string;
  card_known: boolean;
  shared_card_users: AdminUser[];
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
  can_cancel?: boolean;
  /** «Вернуть в очередь» is possible until then. */
  undo_until?: string | null;
  /** «Выплачено» needs an override reason: the account is banned or its wallet frozen. */
  paid_needs_override?: boolean;
  risk?: PayoutRisk | null;
}

export function listPayouts(tab: PayoutTab, cursor?: string, q?: string): Promise<PayoutsPage> {
  const params = new URLSearchParams({ status: tab });
  if (cursor) params.set("cursor", cursor);
  if (q) params.set("q", q);
  return session.apiGet<PayoutsPage>(`${BASE}?${params.toString()}`);
}

export function getPayout(id: string): Promise<PayoutDetail> {
  return session.apiGet<PayoutDetail>(`${BASE}/${encodeURIComponent(id)}`);
}

/** The full card number (audited on the API side; claims the request). Never keep it beyond
 * the page. */
export function revealCard(id: string, purpose: "show" | "copy"): Promise<{ number: string }> {
  return session.apiPost<{ number: string }>(`${BASE}/${encodeURIComponent(id)}/reveal`, {
    purpose,
  });
}

function post(id: string, action: string, body: unknown, key: string): Promise<PayoutDetail> {
  return session.apiPost<PayoutDetail>(`${BASE}/${encodeURIComponent(id)}/${action}`, body, {
    idempotencyKey: key,
  });
}

/** «Беру в работу» (`takeover`: from another admin). */
export function claimPayout(id: string, takeover: boolean, key: string): Promise<PayoutDetail> {
  return post(id, "claim", { takeover }, key);
}

/** «Отпустить». */
export function releasePayout(id: string, key: string): Promise<PayoutDetail> {
  return post(id, "release", {}, key);
}

export function markPaid(
  id: string,
  note: string | null,
  key: string,
  overrideReason: string | null = null,
): Promise<PayoutDetail> {
  return post(id, "paid", { note, override_reason: overrideReason }, key);
}

export function rejectPayout(id: string, reason: string, key: string): Promise<PayoutDetail> {
  return post(id, "reject", { reason }, key);
}

/** «Отменить (откат)»: the sale was reverted after it became payable. */
export function cancelPayout(id: string, reason: string, key: string): Promise<PayoutDetail> {
  return post(id, "cancel", { reason }, key);
}

/** «Вернуть в очередь»: undo a «Выплачено» / «Отклонить» of the last minutes. */
export function undoPayout(id: string, reason: string, key: string): Promise<PayoutDetail> {
  return post(id, "undo", { reason }, key);
}
