/** Admin «P2P» API: `/api/v1/admin/p2p` (spec 2026-10-19-p2p-topup). Mirrors the API's schemas. */
import { session } from "@/lib/api";

const BASE = "/api/v1/admin/p2p";

export interface P2PCard {
  id: string;
  label: string;
  masked: string;
  holder_name: string;
  network: "humo" | "uzcard";
  active: boolean;
  min_amount_uzs: string;
  max_amount_uzs: string;
  daily_limit_uzs: string | null;
  today_uzs: string;
  created_at: string;
}

export interface NewCard {
  label: string;
  pan: string;
  holder_name: string;
  network: "humo" | "uzcard";
  min_amount_uzs: number;
  max_amount_uzs: number;
  daily_limit_uzs: number | null;
}

export interface CardPatch {
  active?: boolean;
  label?: string;
  min_amount_uzs?: number;
  max_amount_uzs?: number;
  daily_limit_uzs?: number;
  no_daily_limit?: boolean;
}

export type IncomingResult = "matched" | "unmatched" | "ignored";

export interface Incoming {
  id: string;
  kind: "credit" | "debit" | "unparsed";
  amount_uzs: string | null;
  card_last4: string | null;
  source_text: string | null;
  bank_time: string | null;
  balance_after: string | null;
  chain_ok: boolean | null;
  result: IncomingResult;
  number: string | null;
  received_at: string;
  can_credit: boolean;
}

export type RequestStatus = "pending" | "paid" | "expired" | "cancelled";

export interface P2PRequest {
  number: string;
  status: RequestStatus;
  amount_uzs: string;
  card_masked: string;
  user: { id: string; display_name: string | null; avatar_url: string | null };
  created_at: string;
  expires_at: string;
  closed_at: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface P2PSettings {
  humo_bot_user_id: number | null;
  owner_telegram_user_id: number | null;
  min_amount_uzs: number;
  max_amount_uzs: number;
  daily_count: number;
  daily_amount_uzs: number;
}

export interface P2PSettingsOut extends P2PSettings {
  connected: boolean;
  last_received_at: string | null;
  updated_at: string;
}

function query(params: Record<string, string | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function listCards(): Promise<{ items: P2PCard[] }> {
  return session.apiGet<{ items: P2PCard[] }>(`${BASE}/cards`);
}

export function addCard(body: NewCard, key: string): Promise<P2PCard> {
  return session.apiPost<P2PCard>(`${BASE}/cards`, body, { idempotencyKey: key });
}

export function patchCard(id: string, body: CardPatch, key: string): Promise<P2PCard> {
  return session.apiPatch<P2PCard>(`${BASE}/cards/${encodeURIComponent(id)}`, body, {
    idempotencyKey: key,
  });
}

export function listIncoming(p: {
  amount?: string;
  result?: IncomingResult;
  cursor?: string;
}): Promise<Page<Incoming>> {
  return session.apiGet<Page<Incoming>>(`${BASE}/incoming${query(p)}`);
}

export function listRequests(p: {
  status?: RequestStatus;
  cursor?: string;
}): Promise<Page<P2PRequest>> {
  return session.apiGet<Page<P2PRequest>>(`${BASE}/requests${query(p)}`);
}

export function getP2PSettings(): Promise<P2PSettingsOut> {
  return session.apiGet<P2PSettingsOut>(`${BASE}/settings`);
}

export function saveP2PSettings(body: P2PSettings, key: string): Promise<P2PSettingsOut> {
  return session.api<P2PSettingsOut>(`${BASE}/settings`, {
    method: "PUT",
    body,
    idempotencyKey: key,
  });
}

export function creditIncoming(
  id: string,
  body: { user_id: string; note: string },
  key: string,
): Promise<{ incoming: Incoming; topup_number: string }> {
  return session.apiPost(`${BASE}/incoming/${encodeURIComponent(id)}/credit`, body, {
    idempotencyKey: key,
  });
}
