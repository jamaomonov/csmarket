import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_ROW } from "./fixtures";
import { PayoutsPage } from "./PayoutsPage";

const api = vi.hoisted(() => ({ listPayouts: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderPage(url = "/payouts") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <PayoutsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PayoutsPage", () => {
  beforeEach(() => {
    api.listPayouts.mockReset().mockResolvedValue({
      items: [PAYOUT_ROW],
      counts: { to_pay: 1, waiting_hold: 2, paid: 5, rejected: 0, canceled: 1 },
      next_cursor: null,
    });
  });

  it("opens on «К выплате» with every tab's count", async () => {
    renderPage();
    expect(await screen.findByRole("link", { name: "К выплате 1" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Ждут 7 дней 2" })).toHaveAttribute(
      "href",
      "/payouts?status=waiting_hold",
    );
    expect(api.listPayouts).toHaveBeenCalledWith("to_pay", undefined);
  });

  it("shows the sale, the user, the masked card, the amount and since when", async () => {
    renderPage();
    const link = await screen.findByRole("link", { name: "S7K2M9QX" });
    expect(link).toHaveAttribute("href", "/payouts/p-1");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText("Humo •••• 9015")).toBeInTheDocument();
    expect(within(row).getByText(/147\s400 сум/)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");
  });

  it("reads the tab from the URL", async () => {
    renderPage("/payouts?status=paid");
    await screen.findByRole("link", { name: "S7K2M9QX" });
    expect(api.listPayouts).toHaveBeenCalledWith("paid", undefined);
  });
});
