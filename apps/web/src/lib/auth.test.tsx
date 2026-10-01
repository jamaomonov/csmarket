// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { session } from "./api";
import { AuthProvider, useAuth } from "./auth";

const HINT = "csmarket.web.has_session";

function Probe() {
  return <p data-testid="status">{useAuth().status}</p>;
}

function renderProvider() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const refreshCalls = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/auth/refresh")).length;

describe("AuthProvider boot", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 401 })));
    vi.stubGlobal("fetch", fetchMock);
    localStorage.setItem(HINT, "1");
  });
  afterEach(() => {
    // The client is a module singleton: never carry a suspended state into the next test.
    session.clearSession();
    vi.unstubAllGlobals();
    localStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("re-mints the session from the cookie when a hint is set", async () => {
    window.history.replaceState(null, "", "/");
    renderProvider();
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("anonymous");
    });
    expect(refreshCalls(fetchMock)).toBe(1);
  });

  it("does not refresh on the Steam return, whatever hydrates first", async () => {
    window.history.replaceState(null, "", "/auth/steam/callback?locale=ru&openid.mode=id_res");
    renderProvider();
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("anonymous");
    });
    expect(refreshCalls(fetchMock)).toBe(0);
    expect(localStorage.getItem(HINT)).toBe("1");
  });

  it("a refresh refused as suspended shows the account as blocked", async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/api/v1/auth/refresh")
          ? new Response(
              JSON.stringify({
                type: "https://csmarket.uz/errors/account-suspended",
                title: "Account suspended",
                status: 403,
              }),
              { status: 403, headers: { "Content-Type": "application/problem+json" } },
            )
          : new Response(null, { status: 204 }),
      ),
    );
    renderProvider();
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("suspended");
    });
    // Not signed out: the next load asks the server again rather than trusting a flag.
    expect(localStorage.getItem(HINT)).toBe("1");
    const logouts = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/logout"));
    expect(logouts).toHaveLength(0);
  });

  it("any other 403 on refresh is signed out", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ status: 403 }), { status: 403 })),
    );
    renderProvider();
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("anonymous");
    });
    expect(localStorage.getItem(HINT)).toBeNull();
  });
});
