/** Admin «Обмены» API: every order as a trade, whatever its source, with the tab counts. */
import { type TradeRowState, type TradeSource, type TradeView } from "./kinds";
import { type AttentionReason, type FailureReason, type OrderStatus } from "../orders/kinds";

import { session } from "@/lib/api";

const BASE = "/api/v1/admin/trades";

export interface AdminTradeItem {
  /** The market name (English). */
  name: string;
  phase: string | null;
  image_url: string | null;
  /** `#rrggbb`. */
  rarity_color: string | null;
  float_value: string | null;
}

export interface AdminTradeBuyer {
  id: string;
  display_name: string | null;
  avatar_url: string | null;
}

export interface AdminTradeRow {
  number: string;
  created_at: string;
  status: OrderStatus;
  source: TradeSource;
  channel: "site" | "api";
  /** The API key owner's name for an `api` order. */
  api_owner: string | null;
  item: AdminTradeItem;
  /** Whole soʻm as digits. */
  price_uzs: string;
  /** USD with six places. */
  price_usd: string;
  /** What the market charged (else the checkout cost), USD. */
  cost_usd: string;
  margin_usd: string;
  /** Of the price, one decimal; `null` for a zero price. */
  margin_pct: string | null;
  paid_with: string | null;
  buyer: AdminTradeBuyer;
  steam_offer_id: string | null;
  offer_url: string | null;
  /** Already masked by the API: the token is never in the page. */
  trade_link_masked: string | null;
  trade_state: TradeRowState;
  /** When Steam's protection of the accepted trade ends. */
  protected_until: string | null;
  /** The end is our estimate (LIS-SKINS names none: accepted + 7 days). */
  protected_estimated: boolean;
  failure_reason: FailureReason | null;
  /** The open (unresolved) attention of any source. */
  attention_reason: AttentionReason | null;
  /** Waxpeer's code as digits, else the purchase's status word. */
  source_status: string | null;
}

export interface AdminTradeCounts {
  all: number;
  active: number;
  hold: number;
  attention: number;
  refunds: number;
}

export interface AdminTradesPage {
  items: AdminTradeRow[];
  counts: AdminTradeCounts;
  next_cursor: string | null;
}

export interface ListTradesParams {
  view?: TradeView;
  q?: string;
  cursor?: string;
}

const PAGE_SIZE = 20;

export function listTrades(p: ListTradesParams = {}): Promise<AdminTradesPage> {
  const params = new URLSearchParams();
  if (p.view) params.set("view", p.view);
  if (p.q) params.set("q", p.q);
  if (p.cursor) params.set("cursor", p.cursor);
  params.set("limit", String(PAGE_SIZE));
  return session.apiGet<AdminTradesPage>(`${BASE}?${params.toString()}`);
}
