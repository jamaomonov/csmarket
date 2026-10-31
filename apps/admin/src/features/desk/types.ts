/** «Мои сделки»: the shapes of `/api/v1/admin/desk` (specs 2026-10-29-desk, 2026-10-31-desk-v2). */
export type Currency = "UZS" | "USD";
export type Method = "direct" | "guarantor";
export type Destination = "skinslink" | "stock";
export type DealStatus = "agreed" | "paid" | "received" | "closed" | "cancelled" | "reverted";
/** The statuses the owner may set by hand; `closed` and `reverted` are the system's. */
export type HandStatus = "agreed" | "paid" | "received" | "cancelled";
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
  /** Who held the money for a `guarantor` deal. */
  guarantor: string | null;
  paid_at: string | null;
  guarantor_released_at: string | null;
  created_at: string;
  updated_at: string;
  items: DeskItem[];
  deposits: DeskDeposit[];
  protected_until: string | null;
  profit_usd: string;
  /** Booked so far plus Skinslink's price less the cost of each skin still bound for it;
   * `null` when cancelled, unpriced or nothing is left for Skinslink. */
  expected_profit_usd: string | null;
  resolved: boolean;
}

export interface DealRow {
  id: string;
  status: DealStatus;
  trader: string;
  method: Method;
  guarantor: string | null;
  note: string | null;
  created_at: string;
  paid_amount: string | null;
  paid_currency: Currency | null;
  paid_usd: string | null;
  items: number;
  /** The dearest skin by Skinslink price. */
  first_item: { name: string; image_url: string | null } | null;
  /** The deal's skins at their Skinslink prices; `null` when none is priced. */
  skinslink_usd: string | null;
  profit_usd: string;
  /** As `Deal.expected_profit_usd`. */
  expected_profit_usd: string | null;
  resolved: boolean;
  protected_until: string | null;
  guarantor_released_at: string | null;
}

export interface Trader {
  trader: string;
  deals: number;
  paid_usd: string;
  profit_usd: string;
  reverts: number;
  last_trade_link: string | null;
  last_deal_at: string;
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
  guarantor?: string;
  items: NewItem[];
}

export interface DealPatch extends Price {
  trader?: string;
  note?: string | null;
  trade_link?: string | null;
  method?: Method;
  guarantor?: string | null;
  status?: HandStatus;
  guarantor_released?: boolean;
}

export interface SellBody {
  where: string;
  amount: string;
  currency: Currency;
  rate?: string;
}
