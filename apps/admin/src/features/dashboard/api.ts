/** Admin dashboard API: `GET /api/v1/admin/dashboard` (M4b). Mirrors the API's schemas. */
import { session } from "@/lib/api";

export type Days = 1 | 7 | 30;

export interface DashboardOut {
  days: number;
  since: string;
  sales: {
    count: number;
    revenue_uzs: string;
    revenue_usd: string;
    cost_usd: string;
    margin_usd: string;
    margin_percent: string;
  };
  refunds: { count: number; amount_uzs: string };
  in_flight: number;
  /** Payments waiting for an operator's decision («На проверке»). */
  holds_open?: number;
  /** Bad reviews no admin has resolved («Отзывы»). */
  reviews_bad_open?: number;
  attention: number;
  /** `sales_attention`: sales with an open attention («Выкуп» → «Продажи», «Проверено»). */
  payouts: { to_pay_count: number; to_pay_uzs: string; sales_attention?: number };
  by_day: { day: string; sales_count: number; revenue_uzs: string; margin_usd: string }[];
  waxpeer: { balance_usd: string | null; read_at: string | null };
  skinslink: { available_usd: string | null; hold_usd: string | null; read_at: string | null };
  lisskins: { available_usd: string | null; locked_usd: string | null; read_at: string | null };
  /** «Выкуп» (spec 2026-10-13-sales-pnl); optional for an API from before it. */
  sales_pnl?: SalesPnlOut;
}

export interface SalesPnlOut {
  count: number;
  income_usd: string;
  to_cards_uzs: string;
  to_balances_uzs: string;
  to_pay_uzs: string;
  withheld_uzs: string;
  bank_uzs: string;
  cost_uzs: string;
  cost_usd: string;
  profit_usd: string;
  profit_percent: string;
  by_day: { day: string; count: number; income_usd: string; profit_usd: string }[];
}

export function getDashboard(days: Days): Promise<DashboardOut> {
  return session.apiGet<DashboardOut>(`/api/v1/admin/dashboard?days=${String(days)}`);
}
