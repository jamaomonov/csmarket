/**
 * Server-side API access for Server Components and route handlers (never imported by a
 * client component): one `fetch` against the internal API origin, cached by Next's data
 * cache. The skins API is locale-free, so one URL is one cache entry.
 *
 * These calls reach `http://api:8000` from the web container, so without help the API
 * keys every visitor's render on the container's one address (SEC-01). A `perVisitor`
 * call names the visitor in `X-Storefront-Client-Ip` beside the shared secret
 * `CSMARKET_STOREFRONT_SECRET` (server-only, never `NEXT_PUBLIC_`), and the API's limiters
 * key it on that visitor (ADR-0003, `csmarket.core.client_ip`).
 */

import { unstable_cache } from "next/cache";
import { headers } from "next/headers";

const ORIGIN = (
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8100"
).replace(/\/$/, "");

/** The headers the API trusts a visitor IP from (`csmarket.core.client_ip`). */
export const STOREFRONT_SECRET_HEADER = "X-Storefront-Secret";
export const STOREFRONT_CLIENT_IP_HEADER = "X-Storefront-Client-Ip";

const IPV4 = /^(\d{1,3}\.){3}\d{1,3}$/;
const IPV6 = /^[0-9a-f:.]+$/i;

/** A non-2xx answer from the API. */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(status: number, path: string) {
    super(`API ${String(status)} for ${path}`);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
  }
}

export interface ApiGetOptions {
  /** Seconds the data cache keeps the answer (default 60). */
  revalidate?: number;
  /** Cache tags for on-demand invalidation (default `["skins"]`). */
  tags?: string[];
  /** Skip the data cache: the answer is as fresh as the API (an admin hide shows at once). */
  noStore?: boolean;
  /**
   * Charge the API call to the visitor being rendered for, not to the web container. Only
   * from a request-time (dynamic) route: it reads the request headers, which would turn a
   * static or ISR route dynamic. A cached answer stays one entry for every visitor; a miss
   * is charged to the visitor who caused it.
   */
  perVisitor?: boolean;
}

/**
 * The visitor's address: the first `X-Forwarded-For` entry, which our Caddy sets to the
 * client (Cloudflare's `Cf-Connecting-Ip`, ADR-0003). `null` when absent or not an IP.
 */
export function visitorIp(h: Pick<Headers, "get">): string | null {
  const first = h.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "";
  if (IPV4.test(first) || (first.includes(":") && IPV6.test(first))) return first;
  return null;
}

/** The trusted-visitor headers, or none when there is no secret or no visitor. */
export function storefrontHeaders(
  ip: string | null,
  secret: string | undefined = process.env.CSMARKET_STOREFRONT_SECRET,
): Record<string, string> {
  if (!secret || ip === null) return {};
  return { [STOREFRONT_SECRET_HEADER]: secret, [STOREFRONT_CLIENT_IP_HEADER]: ip };
}

async function fetchJson<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`${ORIGIN}/api/v1${path}`, init);
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T; // the caller names the DTO it asked for
}

/** GET `/api/v1${path}` and parse the JSON. Throws {@link ApiError} on a non-2xx answer. */
export async function apiGet<T>(path: string, opts: ApiGetOptions = {}): Promise<T> {
  const accept = { Accept: "application/json" };
  const visitor = opts.perVisitor ? storefrontHeaders(visitorIp(await headers())) : {};
  const cache = { revalidate: opts.revalidate ?? 60, tags: opts.tags ?? ["skins"] };
  if (opts.noStore) {
    return fetchJson<T>(path, { headers: { ...accept, ...visitor }, cache: "no-store" });
  }
  if (Object.keys(visitor).length === 0) {
    return fetchJson<T>(path, { headers: accept, next: cache });
  }
  // The fetch cache keys on headers: a visitor IP there would split it per visitor. So the
  // shared entry is keyed by the path alone, and the fetch under it carries the visitor.
  const cached = unstable_cache(
    () => fetchJson<T>(path, { headers: { ...accept, ...visitor }, cache: "no-store" }),
    ["server-api", path],
    cache,
  );
  return cached();
}

/**
 * Like {@link apiGet}, but a 404 is `null`. Only a 404: an outage (5xx, network) still
 * throws, so a broken API never renders as «not found» and never gets a cached 404.
 */
export async function apiGetOrNull<T>(path: string, opts: ApiGetOptions = {}): Promise<T | null> {
  try {
    return await apiGet<T>(path, opts);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
