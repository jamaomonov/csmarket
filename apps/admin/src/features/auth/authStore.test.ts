import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "./authStore";

import { ApiError, session } from "@/lib/api";

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.setState({ status: "loading", me: null });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // The client is a module singleton: never carry a suspended state into the next test.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))),
    );
    session.clearSession();
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  it("reads a signed-in admin from /admin/me", async () => {
    vi.spyOn(session, "getAccessToken").mockReturnValue("tok");
    vi.spyOn(session, "apiGet").mockResolvedValue({
      id: "u",
      display_name: "Owner",
      roles: ["admin"],
    });
    await useAuthStore.getState().bootstrap();
    expect(useAuthStore.getState().status).toBe("admin");
    expect(useAuthStore.getState().me?.display_name).toBe("Owner");
  });

  it("tells a banned account from a plain non-admin", async () => {
    vi.spyOn(session, "getAccessToken").mockReturnValue("tok");
    const get = vi.spyOn(session, "apiGet");
    get.mockRejectedValueOnce(
      new ApiError(403, "Forbidden", { type: "https://csmarket.uz/errors/account-suspended" }),
    );
    await useAuthStore.getState().bootstrap();
    expect(useAuthStore.getState().status).toBe("suspended");

    get.mockRejectedValueOnce(new ApiError(403, "Forbidden", { detail: "admin role required" }));
    await useAuthStore.getState().bootstrap();
    expect(useAuthStore.getState().status).toBe("forbidden");
  });

  it("does not refresh on the Steam return, so it can't revoke the new session", async () => {
    window.history.replaceState(null, "", "/auth/steam/callback?openid.mode=id_res");
    vi.spyOn(session, "getAccessToken").mockReturnValue(null);
    vi.spyOn(session, "hasSessionHint").mockReturnValue(true);
    const refresh = vi.spyOn(session, "refreshAccessToken");
    await useAuthStore.getState().bootstrap();
    expect(refresh).not.toHaveBeenCalled();
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it("goes anonymous when the refresh is refused mid-session", async () => {
    useAuthStore.setState({ status: "admin", me: { id: "u", display_name: "O", roles: [] } });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 401 }))),
    );
    await session.refreshAccessToken();
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it("a refresh refused as suspended is «заблокирован», at boot and mid-session", async () => {
    const suspendedAnswer = () =>
      Promise.resolve(
        new Response(
          JSON.stringify({ type: "https://csmarket.uz/errors/account-suspended", status: 403 }),
          { status: 403 },
        ),
      );
    vi.stubGlobal("fetch", vi.fn(suspendedAnswer));
    vi.spyOn(session, "hasSessionHint").mockReturnValue(true);
    await useAuthStore.getState().bootstrap();
    expect(useAuthStore.getState().status).toBe("suspended");

    session.setAccessToken("tok");
    useAuthStore.setState({ status: "admin", me: { id: "u", display_name: "O", roles: [] } });
    await session.refreshAccessToken();
    expect(useAuthStore.getState().status).toBe("suspended");
    expect(session.getAccessToken()).toBeNull();
  });
});
