/** Admin API keys: thin typed wrappers over `/api/v1/admin/api-keys`. Mirrors the API's schemas. */
import { type AdminOrderRow } from "../orders/api";

import { session } from "@/lib/api";

const BASE = "/api/v1/admin/api-keys";

export type Tariff = "retail" | "cost";

export interface AdminKeyLimits {
  read_per_min: number;
  orders_per_min: number;
  feed_per_min: number;
  check_per_min: number;
}

export type LimitName = keyof AdminKeyLimits;

/** The new limits: `null` = the default. */
export type AdminLimitsBody = Record<LimitName, number | null> & { reason: string };

export interface AdminApiKeyRow {
  id: string;
  user: { id: string; display_name: string | null };
  pricing_profile: Tariff;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  orders: number;
  /** Dollars with three decimals: the key's orders that were not refunded. */
  revenue_usd: string;
  /** Dollars with three decimals: likewise the orders that were not refunded. */
  cost_usd: string;
  /** Effective limits per minute. */
  limits: AdminKeyLimits;
  /** Names of the limits the key sets itself; the rest are defaults. */
  custom_limits: LimitName[];
  /** Addresses or CIDRs; empty = any address. */
  ip_allowlist: string[];
}

export interface AdminApiKeysPage {
  items: AdminApiKeyRow[];
  next_cursor: string | null;
}

export interface AdminApiKeyDelivery {
  event: string;
  status: "pending" | "sent" | "failed";
  attempts: number;
  last_status_code: number | null;
  created_at: string;
}

export interface AdminApiKeyCard {
  key: AdminApiKeyRow;
  /** The latest 20 orders, newest first. */
  orders: AdminOrderRow[];
  /** The host only, never the whole URL. */
  webhook: { host: string; last_delivery: AdminApiKeyDelivery | null } | null;
}

export interface ListApiKeysParams {
  q?: string;
  cursor?: string;
}

const PAGE_SIZE = 20;

export function listApiKeys({ q, cursor }: ListApiKeysParams = {}): Promise<AdminApiKeysPage> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (cursor) params.set("cursor", cursor);
  params.set("limit", String(PAGE_SIZE));
  return session.apiGet<AdminApiKeysPage>(`${BASE}?${params.toString()}`);
}

export function getApiKeyCard(id: string): Promise<AdminApiKeyCard> {
  return session.apiGet<AdminApiKeyCard>(`${BASE}/${encodeURIComponent(id)}`);
}

/** Switch the tariff of the next orders. `key` is one per confirmed submission. */
export function setApiKeyTariff(
  id: string,
  pricingProfile: Tariff,
  reason: string,
  key: string,
): Promise<AdminApiKeyCard> {
  return session.apiPut<AdminApiKeyCard>(
    `${BASE}/${encodeURIComponent(id)}/tariff`,
    { pricing_profile: pricingProfile, reason },
    { idempotencyKey: key },
  );
}

export function revokeApiKey(id: string, reason: string, key: string): Promise<AdminApiKeyCard> {
  return session.apiPost<AdminApiKeyCard>(
    `${BASE}/${encodeURIComponent(id)}/revoke`,
    { reason },
    { idempotencyKey: key },
  );
}

/** Set the per-minute limits (`null` = the default). `key` is one per confirmed submission. */
export function setApiKeyLimits(
  id: string,
  body: AdminLimitsBody,
  key: string,
): Promise<AdminApiKeyCard> {
  return session.apiPut<AdminApiKeyCard>(`${BASE}/${encodeURIComponent(id)}/limits`, body, {
    idempotencyKey: key,
  });
}
