/** «Мои сделки»: typed wrappers over `/api/v1/admin/desk` (specs 2026-10-29-desk, -31-desk-v2). */
import {
  type Deal,
  type DealPatch,
  type DealRow,
  type DealStatus,
  type Destination,
  type InventoryItem,
  type NewDeal,
  type NewItem,
  type SellBody,
  type StockItem,
  type Summary,
  type Trader,
  type Withdrawal,
} from "./types";

import { session } from "@/lib/api";

export type * from "./types";

const BASE = "/api/v1/admin/desk";

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

/** «Отправить обмен»: every open Skinslink skin, or only `itemIds`. */
export function sendDeposit(id: string, itemIds?: string[]): Promise<Deal> {
  return session.apiPost<Deal>(
    `${BASE}/deals/${encodeURIComponent(id)}/deposit`,
    itemIds ? { item_ids: itemIds } : {},
    fresh(),
  );
}

export function addItems(id: string, items: NewItem[]): Promise<Deal> {
  return session.apiPost<Deal>(`${BASE}/deals/${encodeURIComponent(id)}/items`, { items }, fresh());
}

export function removeItem(id: string): Promise<Deal> {
  return session.api<Deal>(`${BASE}/items/${encodeURIComponent(id)}`, {
    method: "DELETE",
    ...fresh(),
  });
}

/** A sold or written-off skin back to open. */
export function undoItem(id: string): Promise<Deal> {
  return session.apiPost<Deal>(`${BASE}/items/${encodeURIComponent(id)}/undo`, undefined, fresh());
}

export function listTraders(q: string): Promise<{ items: Trader[] }> {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  return session.apiGet(`${BASE}/traders?${p.toString()}`);
}

/** The stock skins at Skinslink now, `{name: price_usd}`; keyless — it writes nothing. */
export function stockPrices(): Promise<Record<string, string>> {
  return session.apiPost(`${BASE}/stock/prices`, undefined);
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
