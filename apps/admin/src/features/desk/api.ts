/** «Мои сделки»: typed wrappers over `/api/v1/admin/desk` (spec 2026-10-29-desk). */
import { session } from "@/lib/api";

const BASE = "/api/v1/admin/desk";

export type Currency = "UZS" | "USD";
export type Method = "direct" | "guarantor";
export type Destination = "skinslink" | "stock";
export type DealStatus = "agreed" | "paid" | "received" | "closed" | "cancelled" | "reverted";
export type ItemState = "open" | "sent" | "credited" | "sold" | "written_off" | "reverted";

export interface DeskItem {
  id: string;
  name: string;
  asset_id: string | null;
  image_url: string | null;
  skinslink_usd: string | null;
  destination: Destination;
  cost_usd: string | null;
  state: ItemState;
  deposit_id: string | null;
  sold_where: string | null;
  sold_amount: string | null;
  sold_currency: Currency | null;
  sold_usd: string | null;
  resolved_at: string | null;
  note: string | null;
}

export interface DeskDeposit {
  id: string;
  status: string;
  amount_usd: string | null;
  /** The items' Skinslink prices stand in: Skinslink's own figure was not seen. */
  amount_estimated: boolean;
  trade_offer_id: string | null;
  offer_expiry_at: string | null;
  hold_end_date: string | null;
  fail_reason: string | null;
  /** The bot that sends the offer, as Skinslink names it, and its Steam profile. */
  bot_name: string | null;
  bot_steam_id: string | null;
  bot_persona: string | null;
  bot_avatar_url: string | null;
  accepted_at: string | null;
  credited_at: string | null;
  reverted_at: string | null;
  created_at: string;
}

export interface Deal {
  id: string;
  status: DealStatus;
  trader: string;
  note: string | null;
  trade_link: string | null;
  paid_amount: string | null;
  paid_currency: Currency | null;
  rate: string | null;
  paid_usd: string | null;
  method: Method;
  paid_at: string | null;
  guarantor_released_at: string | null;
  created_at: string;
  updated_at: string;
  items: DeskItem[];
  deposits: DeskDeposit[];
  protected_until: string | null;
  profit_usd: string;
  resolved: boolean;
}

export interface DealRow {
  id: string;
  status: DealStatus;
  trader: string;
  method: Method;
  created_at: string;
  paid_amount: string | null;
  paid_currency: Currency | null;
  paid_usd: string | null;
  items: number;
  profit_usd: string;
  resolved: boolean;
}

export interface Summary {
  profit_usd: string;
  revenue_usd: string;
  deals_closed: number;
  items_resolved: number;
  in_transit_usd: string;
  stock_usd: string;
  skinslink_share_usd: string;
}

export interface InventoryItem {
  asset_id: string;
  name: string;
  image_url: string | null;
  price_usd: string;
}

export interface StockItem extends DeskItem {
  deal_id: string;
  trader: string;
  bought_at: string;
}

export interface Withdrawal {
  id: string;
  amount_usd: string;
  note: string | null;
  at: string;
}

export interface NewItem {
  name: string;
  asset_id?: string;
  image_url?: string;
  skinslink_usd?: string;
  destination: Destination;
}

export interface Price {
  paid_amount?: string | null;
  paid_currency?: Currency | null;
  rate?: string | null;
  paid_at?: string | null;
}

export interface NewDeal extends Price {
  trader: string;
  note?: string;
  trade_link?: string;
  method: Method;
  items: NewItem[];
}

export interface DealPatch extends Price {
  trader?: string;
  note?: string | null;
  trade_link?: string | null;
  method?: Method;
  status?: DealStatus;
  guarantor_released?: boolean;
}

export interface SellBody {
  where: string;
  amount: string;
  currency: Currency;
  rate?: string;
}

export const DESK_KEY = ["admin", "desk"] as const;

/** A fresh key per action: a retry of the same click is the caller's, not ours. */
function fresh(): { idempotencyKey: string } {
  return { idempotencyKey: crypto.randomUUID() };
}

export function getSummary(from?: string, to?: string): Promise<Summary> {
  const p = new URLSearchParams();
  if (from) p.set("from", from);
  if (to) p.set("to", to);
  return session.apiGet<Summary>(`${BASE}/summary?${p.toString()}`);
}

export function listDeals(
  params: { status?: DealStatus; q?: string; cursor?: string } = {},
): Promise<{ items: DealRow[]; next_cursor: string | null }> {
  const p = new URLSearchParams();
  if (params.status) p.set("status", params.status);
  if (params.q) p.set("q", params.q);
  if (params.cursor) p.set("cursor", params.cursor);
  return session.apiGet(`${BASE}/deals?${p.toString()}`);
}

export function getDeal(id: string): Promise<Deal> {
  return session.apiGet<Deal>(`${BASE}/deals/${encodeURIComponent(id)}`);
}

export function createDeal(body: NewDeal): Promise<Deal> {
  return session.apiPost<Deal>(`${BASE}/deals`, body, fresh());
}

export function patchDeal(id: string, body: DealPatch): Promise<Deal> {
  return session.apiPatch<Deal>(`${BASE}/deals/${encodeURIComponent(id)}`, body, fresh());
}

export function sendDeposit(id: string): Promise<Deal> {
  return session.apiPost<Deal>(`${BASE}/deals/${encodeURIComponent(id)}/deposit`, {}, fresh());
}

export function sellItem(id: string, body: SellBody): Promise<Deal> {
  return session.apiPost<Deal>(`${BASE}/items/${encodeURIComponent(id)}/sell`, body, fresh());
}

export function moveItem(id: string, destination: Destination): Promise<Deal> {
  return session.apiPost<Deal>(
    `${BASE}/items/${encodeURIComponent(id)}/move`,
    { destination },
    fresh(),
  );
}

export function writeOff(id: string, note: string): Promise<Deal> {
  return session.apiPost<Deal>(
    `${BASE}/items/${encodeURIComponent(id)}/write-off`,
    { note },
    fresh(),
  );
}

export function listStock(): Promise<{ items: StockItem[]; total_cost_usd: string }> {
  return session.apiGet(`${BASE}/stock`);
}

export function addWithdrawal(amount_usd: string, note?: string): Promise<Withdrawal> {
  return session.apiPost<Withdrawal>(
    `${BASE}/withdrawals`,
    { amount_usd, ...(note ? { note } : {}) },
    fresh(),
  );
}

export function listWithdrawals(): Promise<{ items: Withdrawal[] }> {
  return session.apiGet(`${BASE}/withdrawals`);
}

export function loadInventory(trade_link: string): Promise<{ items: InventoryItem[] }> {
  return session.apiPost(`${BASE}/inventory`, { trade_link });
}

export function getRate(): Promise<{ usd_uzs: string | null }> {
  return session.apiGet(`${BASE}/rate`);
}
