/** Admin audit-log API: a typed wrapper over `GET /api/v1/admin/audit`. Mirrors the API's schema. */
import { session } from "@/lib/api";

export interface AuditRow {
  id: string;
  created_at: string;
  /** Dotted `<module>.<thing>.<verb>`, e.g. `users.ban`. */
  action: string;
  target_type: string;
  target_id: string;
  actor: { id: string; display_name: string | null };
  /** Flat scalars as written by the audit call: a reason, an amount, a slug. Never PII. */
  payload: Record<string, unknown>;
}

export interface AuditPage {
  items: AuditRow[];
  next_cursor: string | null;
}

export interface ListAuditParams {
  action?: string;
  target_type?: string;
  target_id?: string;
  cursor?: string;
}

const PAGE_SIZE = 20;

export function listAudit(p: ListAuditParams = {}): Promise<AuditPage> {
  const params = new URLSearchParams();
  if (p.action) params.set("action", p.action);
  if (p.target_type) params.set("target_type", p.target_type);
  if (p.target_id) params.set("target_id", p.target_id);
  if (p.cursor) params.set("cursor", p.cursor);
  params.set("limit", String(PAGE_SIZE));
  return session.apiGet<AuditPage>(`/api/v1/admin/audit?${params.toString()}`);
}
