import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserReferralBlock } from "./UserReferralBlock";

const api = vi.hoisted(() => ({ getUserReferral: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderBlock() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UserReferralBlock userId="u1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("UserReferralBlock", () => {
  beforeEach(() => {
    api.getUserReferral.mockReset();
  });

  it("names the partner who brought the account", async () => {
    api.getUserReferral.mockResolvedValue({
      partner: { user_id: "p1", code: "zufarmax", display_name: "ZufarMax" },
      attributed_at: "2026-10-27T10:00:00Z",
      is_partner: false,
    });
    renderBlock();
    const link = await screen.findByRole("link", { name: /ZufarMax/ });
    expect(link).toHaveAttribute("href", "/partners/p1");
    expect(screen.getByRole("button", { name: "Сделать партнёром" })).toBeInTheDocument();
  });

  it("says the account came by itself", async () => {
    api.getUserReferral.mockResolvedValue({
      partner: null,
      attributed_at: null,
      is_partner: false,
    });
    renderBlock();
    expect(await screen.findByText("Пришёл сам")).toBeInTheDocument();
  });

  it("links a partner to its own page", async () => {
    api.getUserReferral.mockResolvedValue({ partner: null, attributed_at: null, is_partner: true });
    renderBlock();
    expect(await screen.findByRole("link", { name: "Страница партнёра" })).toHaveAttribute(
      "href",
      "/partners/u1",
    );
    expect(screen.queryByRole("button", { name: "Сделать партнёром" })).toBeNull();
  });
});
