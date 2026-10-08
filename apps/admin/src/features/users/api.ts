/** Admin users API: thin typed wrappers over `/api/v1/admin/users`. Mirrors the API's schemas. */
import { type AdminOrderRow } from "../orders/api";

import { session } from "@/lib/api";

const BASE = "/api/v1/admin/users";

export interface AdminUserRow {
  id: string;
  display_name: string | null;
  avatar_url: string | null;
  steam_id: string;
  roles: string[];
  banned_at: string | null;
  created_at: string;
  /** Whole soʻm as a digit string. */
  balance_uzs: string;
}

export interface AdminUsersPage {
  items: AdminUserRow[];
  next_cursor: string | null;
}

export type TradeLinkVerdict = "ok" | "warn" | "bad";
export type TradeLinkReason = "invalid" | "private" | "trade_ban" | "hold" | "unavailable";

export interface AdminUserDetail {
  id: string;
  steam_id: string;
  display_name: string | null;
  avatar_url: string | null;
  email: string | null;
  locale: "ru" | "uz" | "en";
  roles: string[];
  banned_at: string | null;
  ban_reason: string | null;
  created_at: string;
  /** Already masked by the API: the token is never in the card. */
  trade_link_masked: string | null;
  trade_link_verdict: TradeLinkVerdict | null;
  trade_link_reason: TradeLinkReason | null;
  trade_link_checked_at: string | null;
}

export interface AdminEntry {
  id: string;
  kind: string;
  currency: "UZS" | "USD";
  /** Signed whole soʻm, e.g. `"+50000"` or `"-20000"`; `"0"` on a dollar line. */
  amount_uzs: string;
  /** Signed dollars, e.g. `"+250.000"`, on a dollar line; `null` on a soʻm line. */
  amount_usd: string | null;
  created_at: string;
  reference_number: string | null;
  /** `payments`, `admin:<admin id>` or `null`. */
  actor: string | null;
  reason: string | null;
}

export type TopupStatus = "pending" | "succeeded" | "expired" | "reversed";

export interface AdminTopup {
  number: string;
  amount_uzs: string;
  status: TopupStatus;
  provider: string | null;
  created_at: string;
  succeeded_at: string | null;
}

export interface AdminUserCard {
  user: AdminUserDetail;
  balance_uzs: string;
  entries: AdminEntry[];
  topups: AdminTopup[];
  /** The latest 20 orders, newest first. */
  orders: AdminOrderRow[];
  usd_wallet_enabled: boolean;
  /** Dollars with three decimals, e.g. `"250.000"`. */
  balance_usd: string;
  /** The latest 20 dollar lines, newest first. */
  usd_entries: AdminEntry[];
}

export interface ListUsersParams {
  q?: string;
  cursor?: string;
}

const PAGE_SIZE = 20;

export function listUsers({ q, cursor }: ListUsersParams = {}): Promise<AdminUsersPage> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (cursor) params.set("cursor", cursor);
  params.set("limit", String(PAGE_SIZE));
  return session.apiGet<AdminUsersPage>(`${BASE}?${params.toString()}`);
}

export function getUserCard(id: string): Promise<AdminUserCard> {
  return session.apiGet<AdminUserCard>(`${BASE}/${encodeURIComponent(id)}`);
}

/** Block the account and sign it out everywhere. `key` is one per confirmed submission. */
export function banUser(id: string, reason: string, key: string): Promise<AdminUserCard> {
  return session.apiPost<AdminUserCard>(
    `${BASE}/${encodeURIComponent(id)}/ban`,
    { reason },
    { idempotencyKey: key },
  );
}

export function unbanUser(id: string, reason: string, key: string): Promise<AdminUserCard> {
  return session.apiPost<AdminUserCard>(
    `${BASE}/${encodeURIComponent(id)}/unban`,
    { reason },
    { idempotencyKey: key },
  );
}

/** Credit (`amount > 0`) or claw back (`< 0`) whole soʻm. `key` is one per confirmed submission. */
export function adjustBalance(
  id: string,
  amount: number,
  reason: string,
  key: string,
): Promise<AdminUserCard> {
  return session.apiPost<AdminUserCard>(
    `${BASE}/${encodeURIComponent(id)}/wallet/adjust`,
    { amount_uzs: amount, reason },
    { idempotencyKey: key },
  );
}

/** Credit (`"250.000"`) or claw back (`"-30.000"`) dollars. `key` is one per confirmed submission. */
export function adjustUsdBalance(
  id: string,
  amountUsd: string,
  reason: string,
  key: string,
): Promise<AdminUserCard> {
  return session.apiPost<AdminUserCard>(
    `${BASE}/${encodeURIComponent(id)}/wallet/adjust-usd`,
    { amount_usd: amountUsd, reason },
    { idempotencyKey: key },
  );
}

/** Switch the USD wallet on or off. Money left on it stays; conversion and API buying stop. */
export function switchUsdWallet(
  id: string,
  enabled: boolean,
  reason: string,
  key: string,
): Promise<AdminUserCard> {
  return session.apiPut<AdminUserCard>(
    `${BASE}/${encodeURIComponent(id)}/usd-wallet`,
    { enabled, reason },
    { idempotencyKey: key },
  );
}
