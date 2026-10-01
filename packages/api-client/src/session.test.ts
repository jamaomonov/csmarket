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
