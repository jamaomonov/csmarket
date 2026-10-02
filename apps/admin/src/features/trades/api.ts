/** Admin trades API: the orders that have a Waxpeer trade, with the tab counts. */
import { type AdminOrderRow } from "../orders/api";
import { type AttentionReason, type TradeState, type TradeView } from "../orders/kinds";

import { session } from "@/lib/api";

const BASE = "/api/v1/admin/trades";

export interface AdminTradeSummary {
  /** Waxpeer's trade status code; `null` until the buy reached Waxpeer. */
  status: number | null;
  state: TradeState;
  attention_reason: AttentionReason | null;
  send_until: string | null;
}

export interface AdminTradeRow extends AdminOrderRow {
  trade: AdminTradeSummary;
}

export interface AdminTradeCounts {
  active: number;
  attention: number;
}

export interface AdminTradesPage {
  items: AdminTradeRow[];
  counts: AdminTradeCounts;
  next_cursor: string | null;
}

export interface ListTradesParams {
  view?: TradeView;
  cursor?: string;
}

const PAGE_SIZE = 20;

export function listTrades(p: ListTradesParams = {}): Promise<AdminTradesPage> {
  const params = new URLSearchParams();
  if (p.view) params.set("view", p.view);
  if (p.cursor) params.set("cursor", p.cursor);
  params.set("limit", String(PAGE_SIZE));
  return session.apiGet<AdminTradesPage>(`${BASE}?${params.toString()}`);
}
