import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_ROW } from "./fixtures";
import { edgeOf, PayoutsPage } from "./PayoutsPage";

const api = vi.hoisted(() => ({ listPayouts: vi.fn() }));
vi.mock("./payoutsApi", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

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

const TOTALS = {
  to_pay_count: 1,
  to_pay_uzs: "147400",
  paid_today_count: 3,
  paid_today_uzs: "450000",
  rejected_today_count: 1,
};

describe("PayoutsPage", () => {
  beforeEach(() => {
    api.listPayouts.mockReset().mockResolvedValue({
      items: [PAYOUT_ROW],
      counts: { to_pay: 1, waiting_hold: 2, paid: 5, rejected: 0, canceled: 1 },
      totals: TOTALS,
      next_cursor: null,
    });
  });

  it("opens on «К выплате» with every tab's count and the day's totals", async () => {
    renderPage();
    expect(await screen.findByRole("tab", { name: "К выплате 1" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Ждут 7 дней 2" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(screen.getByText("Выплачено сегодня").nextSibling).toHaveTextContent(/3 · 450\s000 сум/);
    expect(api.listPayouts).toHaveBeenCalledWith("to_pay", undefined, undefined);
  });

  it("shows the sale, the user, the masked card, the amount and how long it waits", async () => {
    renderPage();
    const link = await screen.findByRole("link", { name: "S7K2M9QX" });
    expect(link).toHaveAttribute("href", "/payouts/p-1");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText("Humo •••• 9015")).toBeInTheDocument();
    expect(within(row).getByText(/147\s400 сум/)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");
    expect(within(row).getByText(/^ждёт /)).toBeInTheDocument();
  });

  it("shows who is paying a request and its risk flags", async () => {
    api.listPayouts.mockResolvedValue({
      items: [
        {
          ...PAYOUT_ROW,
          claimed_by: { id: "a-2", display_name: "Petr" },
          claimed_until: "2026-10-15T10:15:00Z",
          flags: ["shared_card", "new_account", "seller_reverted"],
        },
      ],
      counts: { to_pay: 1, waiting_hold: 0, paid: 0, rejected: 0, canceled: 0 },
      totals: TOTALS,
      next_cursor: null,
    });
    renderPage();
    expect(await screen.findByText("платит Petr")).toBeInTheDocument();
    expect(screen.getByText("карта у других")).toBeInTheDocument();
    expect(screen.getByText("новый аккаунт")).toBeInTheDocument();
    expect(screen.getByText("продавец отменил обмен")).toBeInTheDocument();
  });

  it("reads the tab from the URL (old links keep working)", async () => {
    renderPage("/payouts?status=paid");
    await screen.findByRole("link", { name: "S7K2M9QX" });
    expect(api.listPayouts).toHaveBeenCalledWith("paid", undefined, undefined);
    expect(screen.getByRole("tab", { name: "Выплачено 5" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("a tab switches the status", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Ждут 7 дней 2" }));
    await waitFor(() => {
      expect(api.listPayouts).toHaveBeenCalledWith("waiting_hold", undefined, undefined);
    });
    expect(screen.getByRole("tab", { name: "Ждут 7 дней 2" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("the search box is in the normal font with a short placeholder", () => {
    renderPage();
    const box = screen.getByRole("searchbox");
    expect(box).toHaveAttribute("placeholder", "Продажа, карта, имя или Steam ID");
    expect(box).not.toHaveClass("font-mono");
  });

  it("searches across every status", async () => {
    renderPage();
    await screen.findByRole("link", { name: "S7K2M9QX" });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "9015" } });
    await waitFor(() => {
      expect(api.listPayouts).toHaveBeenCalledWith("all", undefined, "9015");
    });
    expect(screen.getByText("Поиск по всем статусам.")).toBeInTheDocument();
  });

  it("tints a card's edge by waiting time: orange after 6 h, red after 10 h", () => {
    const ago = (h: number): string => new Date(Date.now() - h * 3_600_000).toISOString();
    const row = { ...PAYOUT_ROW, status: "to_pay" as const, flags: [] };
    expect(edgeOf({ ...row, to_pay_at: ago(1) })).toBe(false);
    expect(edgeOf({ ...row, to_pay_at: ago(7) })).toBe("warning");
    expect(edgeOf({ ...row, to_pay_at: ago(11) })).toBe(true);
    expect(edgeOf({ ...row, status: "paid" as const, to_pay_at: ago(11) })).toBe(false);
  });
});
