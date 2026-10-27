/**
 * The partner programme (spec 2026-10-27-referrals): the link a visitor came by and the
 * partner's own page, `/api/v1/referrals*`. Amounts are strings of whole soʻm.
 */
import { SessionApiError } from "@csmarket/api-client";

import { API_BASE, session } from "./api";
import { SITE } from "./site";

/** A partner code as the API accepts it. */
export const REF_PATTERN = /^[a-z0-9-]{3,32}$/;
/** The query parameter a partner's link carries. */
export const REF_PARAM = "ref";
export const PARTNER_KEY = ["referrals", "me"] as const;
export const REWARDS_KEY = ["referrals", "rewards"] as const;

export interface Counts {
  visits: number;
  accounts: number;
  purchases: number;
  earned_uzs: string;
}

/** `PartnerMeOut`. */
export interface PartnerMe {
  code: string;
  percent: string;
  /** Months a referred account earns; `null` = forever. */
  term_months: number | null;
  active: boolean;
  month: Counts;
  all_time: Counts;
  held_uzs: string;
  next_available_at: string | null;
  credited_uzs: string;
}

export type RewardStatus = "held" | "credited" | "cancelled";

export interface PartnerReward {
  delivered_at: string;
  base_uzs: string;
  amount_uzs: string;
  status: RewardStatus;
  available_at: string;
}

export interface PartnerRewards {
  items: PartnerReward[];
  next_cursor: string | null;
}

/** Whether the signed-in account is a partner (the admin gives the role). */
export function isPartner(user: { roles: string[] } | null | undefined): boolean {
  return user?.roles.includes("partner") ?? false;
}

/** The link a partner shares. */
export function partnerLink(code: string): string {
  return `${SITE}/?${REF_PARAM}=${encodeURIComponent(code)}`;
}

/** `search` without `ref` (`""` when nothing is left). */
export function withoutRef(search: string): string {
  const params = new URLSearchParams(search);
  params.delete(REF_PARAM);
  const rest = params.toString();
  return rest ? `?${rest}` : "";
}

/** `POST /referrals/visit`: remember the link (a cookie on the API host); errors are ignored. */
export function rememberVisit(code: string): void {
  void fetch(`${API_BASE}/api/v1/referrals/visit`, {
    method: "POST",
    credentials: "include",
    keepalive: true,
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code }),
  }).catch(() => undefined);
}

/** `GET /referrals/me`; `null` when the account is not a partner. */
export async function getPartner(): Promise<PartnerMe | null> {
  try {
    return await session.apiGet<PartnerMe>("/api/v1/referrals/me");
  } catch (err) {
    if (err instanceof SessionApiError && err.status === 404) return null;
    throw err;
  }
}

/** `GET /referrals/me/rewards`, 20 a page. */
export function getRewards(cursor?: string): Promise<PartnerRewards> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return session.apiGet<PartnerRewards>(`/api/v1/referrals/me/rewards${query}`);
}
