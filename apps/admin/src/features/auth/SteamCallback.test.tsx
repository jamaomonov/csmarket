import { render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SteamCallback } from "./SteamCallback";

const mocks = vi.hoisted(() => ({
  completeSteam: vi.fn<(params: Record<string, string>) => Promise<void>>(),
}));

vi.mock("./authStore", () => ({
  loginHref: () => "/api/v1/auth/steam/start?app=admin&locale=ru",
  useAuthStore: (select: (s: { completeSteam: typeof mocks.completeSteam }) => unknown) =>
    select({ completeSteam: mocks.completeSteam }),
}));

/** What Steam appends to our `return_to` (fake id, fake signature). */
const ASSERTION = {
  "openid.ns": "http://specs.openid.net/auth/2.0",
  "openid.mode": "id_res",
  "openid.claimed_id": "https://steamcommunity.com/openid/id/76561198000000001",
  "openid.identity": "https://steamcommunity.com/openid/id/76561198000000001",
  "openid.return_to": "http://localhost:3102/auth/steam/callback?locale=ru&n=fake-nonce",
  "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle",
  "openid.sig": "ZmFrZQ==",
};

function renderCallback() {
  const query = new URLSearchParams({ locale: "ru", n: "fake-nonce", ...ASSERTION });
  window.history.replaceState(null, "", `/auth/steam/callback?${query.toString()}`);
  render(
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<p>Админка</p>} />
        <Route path="/auth/steam/callback" element={<SteamCallback />} />
      </Routes>
    </BrowserRouter>,
  );
}

describe("SteamCallback (admin)", () => {
  beforeEach(() => {
    mocks.completeSteam.mockReset();
  });
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("forwards exactly the openid.* params and strips them from the address bar", async () => {
    let seenSearch: string | null = null;
    mocks.completeSteam.mockImplementation(() => {
      seenSearch = window.location.search;
      return new Promise<void>(() => undefined); // still signing in
    });
    renderCallback();
    await waitFor(() => {
      expect(mocks.completeSteam).toHaveBeenCalledOnce();
    });
    expect(mocks.completeSteam).toHaveBeenCalledWith(ASSERTION);
    expect(seenSearch).toBe(""); // stripped before the API call
    expect(window.location.pathname).toBe("/auth/steam/callback");
    expect(screen.getByText("Входим через Steam…")).toBeInTheDocument();
  });

  it("goes to the admin home once signed in", async () => {
    mocks.completeSteam.mockResolvedValue(undefined);
    renderCallback();
    expect(await screen.findByText("Админка")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });

  it("offers a retry when the sign-in fails", async () => {
    mocks.completeSteam.mockRejectedValue(new Error("401"));
    renderCallback();
    const retry = await screen.findByRole("link", { name: "Попробовать ещё раз" });
    expect(retry.getAttribute("href")).toBe("/api/v1/auth/steam/start?app=admin&locale=ru");
    expect(screen.getByText("Не получилось войти через Steam.")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/auth/steam/callback");
  });
});
