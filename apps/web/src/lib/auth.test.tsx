// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
});
