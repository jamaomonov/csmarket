/** Admin partners API (spec 2026-10-27-referrals): `/api/v1/admin/referrals*`. Mirrors the API. */
import { session } from "@/lib/api";

export interface PartnerTotals {
  visits: number;
  accounts: number;
  purchases: number;
  revenue_uzs: string;
  held_uzs: string;
  credited_uzs: string;
}

export interface AdminPartner {
  user_id: string;
  display_name: string | null;
  steam_id: string;
  code: string;
  /** One decimal, as the API sends it: `"1.5"`. */
  percent: string;
  /** Months a referred account earns; `null` = forever. */
  term_months: number | null;
  active: boolean;
  note: string | null;
  created_at: string;
  totals: PartnerTotals;
}

export interface PartnerMonth {
  month: string;
  visits: number;
  accounts: number;
  purchases: number;
  revenue_uzs: string;
  earned_uzs: string;
}

export type RewardStatus = "held" | "credited" | "cancelled";

export interface AdminReward {
  order_number: string;
  delivered_at: string;
  base_uzs: string;
  percent: string;
  amount_uzs: string;
  status: RewardStatus;
  available_at: string;
  credited_at: string | null;
  cancelled_reason: string | null;
}

export interface PartnerDetail {
  partner: AdminPartner;
  months: PartnerMonth[];
  rewards: AdminReward[];
  next_cursor: string | null;
}

export interface UserReferral {
  partner: { user_id: string; code: string; display_name: string | null } | null;
  attributed_at: string | null;
  is_partner: boolean;
}

/** «Сделать партнёром». */
export interface PartnerInput {
  code: string;
  percent: string;
  term_months: number | null;
  note: string | null;
}

/** Any subset of the terms; `term_months: null` = forever. */
export type PartnerPatch = Partial<PartnerInput & { active: boolean }>;

export const PARTNERS_KEY = ["admin", "referrals"] as const;
const BASE = "/api/v1/admin/referrals";

export const getPartners = (): Promise<{ items: AdminPartner[] }> =>
  session.apiGet<{ items: AdminPartner[] }>(`${BASE}/partners`);

export function getPartner(userId: string, cursor: string | null): Promise<PartnerDetail> {
  const q = cursor === null ? "" : `?cursor=${encodeURIComponent(cursor)}`;
  return session.apiGet<PartnerDetail>(`${BASE}/partners/${encodeURIComponent(userId)}${q}`);
}

export const createPartner = (
  userId: string,
  input: PartnerInput,
  key: string,
): Promise<AdminPartner> =>
  session.apiPost<AdminPartner>(
    `${BASE}/partners`,
    { user_id: userId, ...input },
    { idempotencyKey: key },
  );

export const updatePartner = (
  userId: string,
  patch: PartnerPatch,
  key: string,
): Promise<AdminPartner> =>
  session.apiPatch<AdminPartner>(`${BASE}/partners/${encodeURIComponent(userId)}`, patch, {
    idempotencyKey: key,
  });

export const getUserReferral = (userId: string): Promise<UserReferral> =>
  session.apiGet<UserReferral>(`${BASE}/users/${encodeURIComponent(userId)}`);
