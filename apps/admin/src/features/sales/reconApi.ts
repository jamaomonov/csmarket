/** «Сверка»: `GET /api/v1/admin/sales/reconciliation` (spec 2026-10-13-sales-pnl). */
import { type SaleStatus } from "./api";

import { session } from "@/lib/api";

export type ReconDays = 1 | 7 | 30;
export type ReconFlag = "short" | "missing" | "reverted";

export interface ReconRow {
  number: string;
  status: SaleStatus;
  done_at: string | null;
  trade_id: number | null;
  quoted_usd: string;
  amount_usd: string | null;
  diff_usd: string | null;
  flag: ReconFlag | null;
}

export interface ReconPage {
  items: ReconRow[];
  next_cursor: string | null;
  expected_usd: string;
  credited_usd: string;
  diff_usd: string;
  problems: number;
}

export const FLAG_LABELS: Record<ReconFlag, string> = {
  short: "Недозачислено",
  missing: "Нет зачисления",
  reverted: "Откат",
};

export const RECON_KEY = ["admin", "sales", "reconciliation"] as const;

export function getReconciliation(p: {
  days: ReconDays;
  problems: boolean;
  cursor?: string;
}): Promise<ReconPage> {
  const params = new URLSearchParams({ days: String(p.days) });
  if (p.problems) params.set("problems", "true");
  if (p.cursor) params.set("cursor", p.cursor);
  return session.apiGet<ReconPage>(`/api/v1/admin/sales/reconciliation?${params.toString()}`);
}
