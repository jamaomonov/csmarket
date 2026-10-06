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
  attention: number;
  by_day: { day: string; sales_count: number; revenue_uzs: string; margin_usd: string }[];
  waxpeer: { balance_usd: string | null; read_at: string | null };
  skinslink: { available_usd: string | null; hold_usd: string | null; read_at: string | null };
}

export function getDashboard(days: Days): Promise<DashboardOut> {
  return session.apiGet<DashboardOut>(`/api/v1/admin/dashboard?days=${String(days)}`);
}
