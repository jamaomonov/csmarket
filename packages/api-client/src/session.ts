/**
 * Browser session client shared by the storefront and the admin SPA.
 *
 * Keeps the access JWT in memory (never localStorage, so an XSS payload can't
 * read it), attaches it as a Bearer header and surfaces non-2xx answers as
 * {@link SessionApiError}. The 30-day refresh token rides an HttpOnly cookie
 * (`credentials: "include"` on every API call); on load the app re-mints the access
 * token from it with {@link SessionClient.refreshAccessToken}.
 *
 * A `401` triggers one refresh and one replay of the original request. The
 * refresh is single-flight: parallel 401s share one in-flight promise in the
 * tab, and the Web Locks API serialises tabs, so the rotating refresh token is
 * never presented twice at once (the server treats reuse as theft). Only a
 * refusal (`401` / `403`) ends the session; a 5xx or a network error keeps it.
 *
 * A refresh refused as `account-suspended` (a banned account, whose sessions the ban
 * revoked) ends the session too, but leaves it **suspended** rather than signed out:
 * no token, and {@link SessionClient.isSuspended} is true, so the app can say why.
 * The hint and the (revoked) cookie are kept and no logout is sent, so every load
 * asks again and the server answers 403 again; nothing about the ban is stored here.
 * A suspended session never refreshes on a 401: it would only hear 403 again.
 *
 * The token and the cookies go only to our API: a path relative to `baseUrl`.
 * An absolute URL is fetched with neither, and its 401 is not ours to refresh.
 *
 * Everything is closed over per client: two clients never share a token.
 */

import { isSuspendedAnswer, readErrorBody, SessionApiError } from "./problem";

export interface SessionClientOptions {
  /** API origin, e.g. `https://api.csmarket.uz`; empty for same-origin. */
  baseUrl: string;
  /** `localStorage` key of the non-secret "a session may exist" flag. */
  hintKey: string;
  /** Web Locks name serialising refreshes across this app's tabs. */
  lockName: string;
}

export interface SessionRequestOptions {
  method?: string;
  /** JSON-encoded when present. */
  body?: unknown;
  headers?: HeadersInit;
  /** Omit the Authorization header even if a token is held. */
  anonymous?: boolean;
  /** Sent as `Idempotency-Key` (≥ 16 chars on state-changing endpoints). */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export interface SessionWriteOptions {
  anonymous?: boolean;
  idempotencyKey?: string;
}

export type SessionReadOptions = Omit<SessionRequestOptions, "method" | "body">;

export interface SessionClient {
  api: <T = unknown>(path: string, init?: SessionRequestOptions) => Promise<T>;
  apiGet: <T = unknown>(path: string, options?: SessionReadOptions) => Promise<T>;
  apiPost: <T = unknown>(path: string, body: unknown, options?: SessionWriteOptions) => Promise<T>;
  apiPatch: <T = unknown>(path: string, body: unknown, options?: SessionWriteOptions) => Promise<T>;
  apiPut: <T = unknown>(path: string, body: unknown, options?: SessionWriteOptions) => Promise<T>;
  getAccessToken: () => string | null;
  /** Hold `token` in memory and set the session hint. */
  setAccessToken: (token: string) => void;
  /** Forget the token and hint; revoke the server session (fire-and-forget). */
  clearSession: () => void;
  /** Whether a prior session may exist — the gate for a silent refresh on load. */
  hasSessionHint: () => boolean;
  /** Re-mint the access token from the refresh cookie; `true` on success. */
  refreshAccessToken: () => Promise<boolean>;
  /** Called when a refresh is refused (the session is dead). Returns an unsubscribe. */
  onAuthLost: (cb: () => void) => () => void;
  /** The last refresh was refused because the account is banned (until a new token or sign-out). */
  isSuspended: () => boolean;
}

/** Build a session client; see the module docstring for the mechanics. */
export function createSessionClient(opts: SessionClientOptions): SessionClient {
  const baseUrl = opts.baseUrl.replace(/\/+$/, "");
  let accessToken: string | null = null;
  let refreshInFlight: Promise<boolean> | null = null;
  let suspended = false;
  const lostListeners = new Set<() => void>();

  const writeHint = (on: boolean): void => {
    try {
      if (on) localStorage.setItem(opts.hintKey, "1");
      else localStorage.removeItem(opts.hintKey);
    } catch {
      /* storage blocked — the in-memory token still works for this tab */
    }
  };

  const setAccessToken = (token: string): void => {
    accessToken = token;
    suspended = false;
    writeHint(true);
  };

  const clearSession = (): void => {
    accessToken = null;
    suspended = false;
    writeHint(false);
    // JS can't delete the HttpOnly cookie; the server revokes and expires it.
    // Fire-and-forget: signing out must never block or throw.
    fetch(`${baseUrl}/api/v1/auth/logout`, { method: "POST", credentials: "include" }).catch(() => {
      /* offline or already revoked — nothing to do */
    });
  };

  const authLost = (): void => {
    clearSession();
    for (const cb of lostListeners) cb();
  };

  /** Banned: drop the token but keep the hint and the cookie (see the module docstring). */
  const suspend = (): void => {
    accessToken = null;
    suspended = true;
    for (const cb of lostListeners) cb();
  };

  const doRefresh = async (): Promise<boolean> => {
    let response: Response;
    try {
      response = await fetch(`${baseUrl}/api/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
    } catch {
      // Network error: keep the session — the visitor may just be offline.
      return false;
    }
    // Only a refusal means the session is dead: 401 (no, unknown, reused or expired
    // cookie) or 403 (suspended). A 5xx / 429 is the API having a bad moment — keep
    // the session, like the network-error branch; clearing it would also POST
    // /auth/logout and revoke a perfectly good 30-day session.
    if (response.status === 403 && (await isSuspendedAnswer(response))) {
      suspend();
      return false;
    }
    if (response.status === 401 || response.status === 403) {
      authLost();
      return false;
    }
    if (!response.ok) return false;
    // Narrowing the refresh endpoint's JSON (`TokensOut`) to the field we read.
    const body = (await response.json().catch(() => null)) as { access_token?: unknown } | null;
    if (typeof body?.access_token !== "string" || !body.access_token) return false;
    setAccessToken(body.access_token);
    return true;
  };

  const refreshAccessToken = (): Promise<boolean> => {
    if (refreshInFlight !== null) return refreshInFlight;
    const run =
      typeof navigator !== "undefined" && "locks" in navigator
        ? () => navigator.locks.request(opts.lockName, doRefresh)
        : doRefresh;
    refreshInFlight = Promise.resolve(run()).finally(() => {
      refreshInFlight = null;
    });
    return refreshInFlight;
  };

  const request = async <T>(
    path: string,
    init: SessionRequestOptions,
    allowRefresh: boolean,
  ): Promise<T> => {
    const { anonymous, idempotencyKey, body, headers, method, signal } = init;
    // Ours = relative to baseUrl. Anything absolute is a third party: no token, no cookies.
    const ours = !path.startsWith("http");
    const url = ours ? `${baseUrl}${path}` : path;
    const h = new Headers(headers);
    h.set("Accept", "application/json");
    if (body !== undefined && !h.has("Content-Type")) h.set("Content-Type", "application/json");
    if (idempotencyKey) h.set("Idempotency-Key", idempotencyKey);
    const sentToken = anonymous || !ours ? null : accessToken;
    if (sentToken) h.set("Authorization", `Bearer ${sentToken}`);

    const response = await fetch(url, {
      method: method ?? "GET",
      headers: h,
      credentials: ours ? "include" : "omit",
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      ...(signal ? { signal } : {}),
    });

    if (
      response.status === 401 &&
      ours &&
      allowRefresh &&
      !anonymous &&
      !suspended &&
      !path.includes("/auth/refresh")
    ) {
      // A parallel call may have rotated the token already: replay with it.
      const ok =
        accessToken !== null && accessToken !== sentToken ? true : await refreshAccessToken();
      if (ok) return request<T>(path, init, false);
    }

    if (!response.ok) {
      throw new SessionApiError(
        response.status,
        response.statusText,
        await readErrorBody(response),
      );
    }
    // 204 carries no body; callers type such endpoints as `undefined`.
    if (response.status === 204) return undefined as T;
    // The API's JSON contract is the caller's `T`.
    return (await response.json()) as T;
  };

  const api = <T = unknown>(path: string, init: SessionRequestOptions = {}): Promise<T> =>
    request<T>(path, init, true);

  const write =
    (method: "POST" | "PATCH" | "PUT") =>
    <T = unknown>(path: string, body: unknown, options: SessionWriteOptions = {}): Promise<T> =>
      api<T>(path, { ...options, method, body });

  return {
    api,
    apiGet: <T = unknown>(path: string, options: SessionReadOptions = {}) => api<T>(path, options),
    apiPost: write("POST"),
    apiPatch: write("PATCH"),
    apiPut: write("PUT"),
    getAccessToken: () => accessToken,
    setAccessToken,
    clearSession,
    hasSessionHint: () => {
      try {
        return localStorage.getItem(opts.hintKey) === "1";
      } catch {
        return false;
      }
    },
    refreshAccessToken,
    isSuspended: () => suspended,
    onAuthLost: (cb) => {
      lostListeners.add(cb);
      return () => {
        lostListeners.delete(cb);
      };
    },
  };
}
