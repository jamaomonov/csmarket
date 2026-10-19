/**
 * Admin analytics API: `GET /api/v1/admin/analytics/{business,calendar,losses}`
 * (spec 2026-10-19-analytics). Mirrors the API's schemas: soʻm whole digits, USD six places,
 * percents one decimal — all strings.
 */
import { session } from "@/lib/api";

const BASE = "/api/v1/admin/analytics";

export type Channel = "all" | "site" | "api";

export interface Money {
  uzs: string;
  usd: string;
}

export interface Totals {
  orders: number;
  revenue: Money;
  cost: Money;
  profit: Money;
  margin_percent: string;
  earned_profit_uzs: string;
  in_flight_profit_uzs: string;
  in_flight_orders: number;
  average_check_uzs: string;
  buyback_profit_uzs: string;
  buyback_profit_usd: string;
  refunds: number;
  refunds_uzs: string;
  new_buyers: number;
  gross_profit_uzs: string;
}

export interface DayOut {
  day: string;
  orders: number;
  revenue_uzs: string;
  earned_profit_uzs: string;
  in_flight_profit_uzs: string;
  buyback_profit_uzs: string;
}

export interface Slice {
  key: string;
  orders: number;
  revenue_uzs: string;
  profit_uzs: string;
  profit_usd: string;
  margin_percent: string;
}

export interface FeeOut {
  provider: string;
  payments: number;
  fee_uzs: string;
}

export interface SkinOut {
  name: string;
  image_url: string | null;
  orders: number;
  revenue_uzs: string;
  profit_uzs: string;
}

export interface CountOut {
  count: number;
  revenue_uzs: string;
}

export interface BuyerOut {
  id: string;
  display_name: string | null;
  avatar_url: string | null;
  orders: number;
  revenue_uzs: string;
  profit_uzs: string;
}

export interface KeyCount {
  key: string;
  count: number;
  amount_uzs: string;
}

export interface BusinessOut {
  since: string;
  until: string;
  channel: Channel;
  totals: Totals;
  previous: Totals;
  by_day: DayOut[];
  sources: Slice[];
  channels: Slice[];
  payments: Slice[];
  kassa_fees: FeeOut[];
  categories: Slice[];
  top_skins: SkinOut[];
  buyers: { new: CountOut; returning: CountOut; top: BuyerOut[] };
  refunds: { count: number; amount_uzs: string; by_source: KeyCount[]; by_reason: KeyCount[] };
  buyback: {
    count: number;
    income_usd: string;
    to_cards_uzs: string;
    to_balances_uzs: string;
    to_pay_uzs: string;
    profit_uzs: string;
    profit_usd: string;
  };
}

export interface CalendarOut {
  month: string;
  channel: Channel;
  days: DayOut[];
}

export interface LossOut {
  number: string;
  name: string;
  source: string;
  paid_at: string;
  revenue_uzs: string;
  cost_uzs: string;
  profit_uzs: string;
}

function query(params: Record<string, string>): string {
  return new URLSearchParams(params).toString();
}

export function getBusiness(since: string, until: string, channel: Channel): Promise<BusinessOut> {
  return session.apiGet<BusinessOut>(`${BASE}/business?${query({ since, until, channel })}`);
}

export function getCalendar(month: string, channel: Channel): Promise<CalendarOut> {
  return session.apiGet<CalendarOut>(`${BASE}/calendar?${query({ month, channel })}`);
}

export function getLosses(
  since: string,
  until: string,
  channel: Channel,
): Promise<{ items: LossOut[] }> {
  return session.apiGet<{ items: LossOut[] }>(`${BASE}/losses?${query({ since, until, channel })}`);
}
