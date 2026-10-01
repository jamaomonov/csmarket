/**
 * Server-side API access for Server Components and route handlers (never imported by a
 * client component): one `fetch` against the internal API origin, cached by Next's data
 * cache. The skins API is locale-free, so one URL is one cache entry.
 */

const ORIGIN = (
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8100"
).replace(/\/$/, "");

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
}

/** GET `/api/v1${path}` and parse the JSON. Throws {@link ApiError} on a non-2xx answer. */
export async function apiGet<T>(path: string, opts: ApiGetOptions = {}): Promise<T> {
  const res = await fetch(`${ORIGIN}/api/v1${path}`, {
    headers: { Accept: "application/json" },
    next: { revalidate: opts.revalidate ?? 60, tags: opts.tags ?? ["skins"] },
  });
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T; // the caller names the DTO it asked for
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
