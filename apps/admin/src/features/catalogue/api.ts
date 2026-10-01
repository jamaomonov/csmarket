/** Admin catalogue API: thin typed wrappers over `/api/v1/admin/skins`. Mirrors the API's schemas. */
import { session } from "@/lib/api";

const BASE = "/api/v1/admin/skins";

export interface JobOut {
  finished_at: string;
  ok: boolean;
  counters: Record<string, number>;
  error: string | null;
}

export interface FxOut {
  usd_uzs: string;
  fetched_at: string;
  source: string;
}

export interface CatalogStatus {
  items_total: number;
  items_active: number;
  items_hidden: number;
  prices_updated_at: string | null;
  import_job: JobOut | null;
  price_sync_job: JobOut | null;
  fx: FxOut | null;
  sync_enabled: boolean;
  waxpeer_key_set: boolean;
}

export interface AdminSkinItem {
  slug: string;
  name: string;
  phase: string | null;
  category: string | null;
  weapon: string | null;
  exterior: string | null;
  stattrak: boolean;
  souvenir: boolean;
  image_url: string | null;
  active: boolean;
  hidden: boolean;
  price_usd: string | null;
  count: number;
}

export interface Alias {
  alias: string;
  text: string;
}

export interface FindItemsParams {
  q?: string;
  hidden?: boolean;
}

/** A fresh key per mutation: a retry of the same click is the caller's, not ours. */
function freshKey(): { idempotencyKey: string } {
  return { idempotencyKey: crypto.randomUUID() };
}

export function getStatus(): Promise<CatalogStatus> {
  return session.apiGet<CatalogStatus>(`${BASE}/catalog/status`);
}

export function findItems({ q, hidden }: FindItemsParams = {}): Promise<{
  items: AdminSkinItem[];
}> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (hidden !== undefined) params.set("hidden", String(hidden));
  params.set("limit", "50");
  return session.apiGet(`${BASE}/items?${params.toString()}`);
}

export function setHidden(slug: string, hidden: boolean): Promise<AdminSkinItem> {
  return session.apiPatch<AdminSkinItem>(
    `${BASE}/items/${encodeURIComponent(slug)}`,
    { hidden },
    freshKey(),
  );
}

export function listAliases(): Promise<{ items: Alias[] }> {
  return session.apiGet(`${BASE}/aliases`);
}

export function putAlias(alias: string, text: string): Promise<Alias> {
  return session.apiPut<Alias>(
    `${BASE}/aliases/${encodeURIComponent(alias)}`,
    { text },
    freshKey(),
  );
}

export async function deleteAlias(alias: string): Promise<void> {
  await session.api<undefined>(`${BASE}/aliases/${encodeURIComponent(alias)}`, {
    method: "DELETE",
    ...freshKey(),
  });
}
