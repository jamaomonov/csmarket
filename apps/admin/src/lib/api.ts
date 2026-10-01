/**
 * Admin's session client: same mechanics as the storefront (shared
 * `createSessionClient`), its own session hint and refresh lock. Same-origin
 * `/api` in dev (Vite proxy), absolute `VITE_API_BASE_URL` in prod.
 */
import { createSessionClient, SessionApiError } from "@csmarket/api-client";

export const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

export const session = createSessionClient({
  baseUrl: apiBase,
  hintKey: "csmarket.admin.has_session",
  lockName: "csmarket-admin-token-refresh",
});

export { SessionApiError as ApiError };

/** The one line of an API failure worth showing an operator. */
export function formatApiError(err: SessionApiError): string {
  // Narrowing an unknown problem+json body to the two fields we read.
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
