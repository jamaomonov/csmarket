import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DETAIL, PARTNER } from "./fixtures";
import { PartnerDetailPage } from "./PartnerDetail";
import { PartnersPage } from "./PartnersPage";

const api = vi.hoisted(() => ({ getPartners: vi.fn(), getPartner: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderAt(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PartnersPage", () => {
  beforeEach(() => {
    api.getPartners.mockReset().mockResolvedValue({ items: [PARTNER] });
    api.getPartner.mockReset().mockResolvedValue(DETAIL);
  });

  it("lists partners with their numbers and links each to its page", async () => {
    renderAt(<PartnersPage />);
    const row = await screen.findByRole("link", { name: /ZufarMax/ });
    expect(row).toHaveAttribute("href", "/partners/u-partner");
    const table = screen.getByRole("table", { name: "Партнёры" });
    expect(within(table).getByText("zufarmax")).toBeInTheDocument();
    expect(table).toHaveTextContent("zufarmax");
    expect(table).toHaveTextContent("1 200 000 сум");
    expect(table).toHaveTextContent("6 мес.");
  });

  it("shows a partner's rewards with links to the orders", async () => {
    renderAt(<PartnerDetailPage userId="u-partner" />);
    const link = await screen.findByRole("link", { name: "DTN44T1E" });
    expect(link).toHaveAttribute("href", "/orders/DTN44T1E");
    expect(screen.getByText("В ожидании")).toBeInTheDocument();
  });
});
