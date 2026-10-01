import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createSessionClient, SessionApiError } from "./session";

const BASE = "http://api.test";

function json(status: number, body: unknown): Response {
  // Fetch forbids a body on a null-body status (204): send none there.
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("createSessionClient", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    localStorage.clear();
  });
  afterEach(() => vi.unstubAllGlobals());

  const make = () => createSessionClient({ baseUrl: BASE, hintKey: "hint", lockName: "lock" });

  it("sends the Bearer token and credentials", async () => {
    const c = make();
    c.setAccessToken("A");
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    await c.apiGet("/api/v1/me");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE}/api/v1/me`);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer A");
    expect(init.credentials).toBe("include");
    expect(localStorage.getItem("hint")).toBe("1");
  });

  it("refreshes once on 401 and replays", async () => {
    const c = make();
    c.setAccessToken("old");
    fetchMock
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(200, { access_token: "new", expires_in: 900 }))
      .mockResolvedValueOnce(json(200, { id: "u" }));
    await expect(c.apiGet<{ id: string }>("/api/v1/me")).resolves.toEqual({ id: "u" });
    expect(c.getAccessToken()).toBe("new");
  });

  it("parallel 401s share one refresh", async () => {
    const c = make();
    c.setAccessToken("old");
    let refreshes = 0;
    fetchMock.mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        refreshes += 1;
        return Promise.resolve(json(200, { access_token: "new", expires_in: 900 }));
      }
      return Promise.resolve(json(c.getAccessToken() === "new" ? 200 : 401, {}));
    });
    await Promise.all([c.apiGet("/a"), c.apiGet("/b"), c.apiGet("/c")]);
    expect(refreshes).toBe(1);
  });

  it("a failed refresh clears the session and fires onAuthLost", async () => {
    const c = make();
    const lost = vi.fn();
    c.onAuthLost(lost);
    c.setAccessToken("old");
    fetchMock
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValue(json(204, {}));
    await expect(c.apiGet("/api/v1/me")).rejects.toBeInstanceOf(SessionApiError);
    expect(lost).toHaveBeenCalledOnce();
    expect(c.getAccessToken()).toBeNull();
    expect(localStorage.getItem("hint")).toBeNull();
  });

  it("a banned account's 403 on refresh is also a lost session", async () => {
    const c = make();
    const lost = vi.fn();
    c.onAuthLost(lost);
    c.setAccessToken("old");
    fetchMock.mockResolvedValueOnce(json(403, {})).mockResolvedValue(json(204, {}));
    await expect(c.refreshAccessToken()).resolves.toBe(false);
    expect(lost).toHaveBeenCalledOnce();
    expect(localStorage.getItem("hint")).toBeNull();
  });

  const SUSPENDED = {
    type: "https://csmarket.uz/errors/account-suspended",
    title: "Account suspended",
    status: 403,
  };
  const urls = () => fetchMock.mock.calls.map((call) => call[0] as string);

  it("a refresh refused as suspended keeps the session distinct from signed out", async () => {
    const c = make();
    const lost = vi.fn();
    c.onAuthLost(lost);
    localStorage.setItem("hint", "1");
    fetchMock.mockResolvedValue(json(403, SUSPENDED));
    await expect(c.refreshAccessToken()).resolves.toBe(false);
    expect(c.isSuspended()).toBe(true);
    expect(c.getAccessToken()).toBeNull();
    expect(lost).toHaveBeenCalledOnce();
    // The hint and the (revoked) cookie stay: the next load asks again and hears 403 again.
    expect(localStorage.getItem("hint")).toBe("1");
    expect(urls().some((u) => u.endsWith("/auth/logout"))).toBe(false);
  });

  it("parallel refreshes refused as suspended share one request", async () => {
    const c = make();
    fetchMock.mockResolvedValue(json(403, SUSPENDED));
    await expect(Promise.all([c.refreshAccessToken(), c.refreshAccessToken()])).resolves.toEqual([
      false,
      false,
    ]);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(c.isSuspended()).toBe(true);
  });

  it("a suspended session does not refresh and replay on a 401", async () => {
    const c = make();
    fetchMock.mockResolvedValueOnce(json(403, SUSPENDED));
    await c.refreshAccessToken();
    fetchMock.mockResolvedValueOnce(json(401, {}));
    await expect(c.apiGet("/api/v1/wallet")).rejects.toMatchObject({ status: 401 });
    expect(urls().filter((u) => u.endsWith("/auth/refresh"))).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("a new token or a sign-out ends the suspended state", async () => {
    const c = make();
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(url.endsWith("/auth/logout") ? json(204, {}) : json(403, SUSPENDED)),
    );
    await c.refreshAccessToken();
    c.setAccessToken("fresh");
    expect(c.isSuspended()).toBe(false);
    c.clearSession();
    await c.refreshAccessToken();
    expect(c.isSuspended()).toBe(true);
    c.clearSession();
    expect(c.isSuspended()).toBe(false);
    expect(localStorage.getItem("hint")).toBeNull();
  });

  it("a 401 or another 403 on refresh is signed out, not suspended", async () => {
    for (const [status, body] of [
      [401, {}],
      [403, {}],
      [403, { type: "https://csmarket.uz/errors/forbidden", status: 403 }],
    ] as const) {
      const c = make();
      const lost = vi.fn();
      c.onAuthLost(lost);
      c.setAccessToken("old");
      fetchMock.mockReset();
      fetchMock.mockResolvedValueOnce(json(status, body)).mockResolvedValue(json(204, {}));
      await expect(c.refreshAccessToken()).resolves.toBe(false);
      expect(c.isSuspended()).toBe(false);
      expect(lost).toHaveBeenCalledOnce();
      expect(localStorage.getItem("hint")).toBeNull();
      expect(urls().some((u) => u.endsWith("/auth/logout"))).toBe(true);
    }
  });

  it.each([500, 502, 503, 429])(
    "a %i on refresh keeps the session: no logout, hint kept",
    async (status) => {
      const c = make();
      const lost = vi.fn();
      c.onAuthLost(lost);
      c.setAccessToken("old");
      fetchMock.mockResolvedValueOnce(json(status, {}));
      await expect(c.refreshAccessToken()).resolves.toBe(false);
      expect(lost).not.toHaveBeenCalled();
      expect(localStorage.getItem("hint")).toBe("1");
      const urls = fetchMock.mock.calls.map((call) => call[0] as string);
      expect(urls.some((u) => u.endsWith("/auth/logout"))).toBe(false);
    },
  );

  it("an absolute URL gets neither the Bearer token nor the cookies", async () => {
    const c = make();
    c.setAccessToken("A");
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    await c.apiGet("https://elsewhere.example/thing");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://elsewhere.example/thing");
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
    expect(init.credentials).toBe("omit");
  });

  it("an absolute URL's 401 does not trigger a refresh", async () => {
    const c = make();
    c.setAccessToken("A");
    fetchMock.mockResolvedValueOnce(json(401, {}));
    await expect(c.apiGet("https://elsewhere.example/thing")).rejects.toBeInstanceOf(
      SessionApiError,
    );
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("exposes problem+json code", async () => {
    const c = make();
    fetchMock.mockResolvedValueOnce(json(422, { code: "trade_link_not_yours", type: "x" }));
    const err = await c
      .apiPut("/api/v1/me/trade-link", { url: "u" }, { idempotencyKey: "k".repeat(20) })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(SessionApiError);
    expect((err as SessionApiError).code).toBe("trade_link_not_yours");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("k".repeat(20));
  });
});
