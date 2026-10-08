import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_DETAIL } from "./fixtures";
import { PayoutDetail } from "./PayoutDetail";

const api = vi.hoisted(() => ({
  getPayout: vi.fn(),
  revealCard: vi.fn(),
  markPaid: vi.fn(),
  rejectPayout: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/payouts/p-1"]}>
        <Routes>
          <Route
            path="/payouts/:id"
            element={
              <>
                <Link to="/payouts/p-2">next</Link>
                <PayoutDetail />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PayoutDetail", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getPayout.mockResolvedValue(PAYOUT_DETAIL);
    api.revealCard.mockResolvedValue({ number: "9860123456789015" });
  });

  it("shows the masked card and the money breakdown, never the number by itself", async () => {
    renderPage();
    expect(await screen.findByText("Humo •••• 9015")).toBeInTheDocument();
    expect(screen.getByText(/155\s200 сум/)).toBeInTheDocument();
    expect(screen.getByText(/−7\s800 сум/)).toBeInTheDocument();
    expect(screen.queryByText(/9860 1234 5678 9015/)).toBeNull();
  });

  it("«Показать» asks the audited reveal", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
    expect(await screen.findByText("9860 1234 5678 9015")).toBeInTheDocument();
    expect(api.revealCard).toHaveBeenCalledWith("p-1", "show");
  });

  it("«Скопировать» reveals for a copy and puts the digits on the clipboard", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Скопировать номер" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("9860123456789015");
    });
    expect(api.revealCard).toHaveBeenCalledWith("p-1", "copy");
  });

  it("«Выплачено» sends the note with a key after a confirm", async () => {
    api.markPaid.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Выплачено" }));
    fireEvent.change(screen.getByLabelText("Комментарий"), { target: { value: "Click #1" } });
    fireEvent.click(screen.getByRole("button", { name: "Да, выплачено" }));
    await waitFor(() => {
      expect(api.markPaid).toHaveBeenCalledWith(
        "p-1",
        "Click #1",
        expect.stringMatching(/^admin-payout-paid-/),
      );
    });
  });

  it("«Отклонить» needs a reason", async () => {
    api.rejectPayout.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отклонить" }));
    const confirm = screen.getByRole("button", { name: "Да, отклонить" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Причина"), {
      target: { value: "Карта заблокирована" },
    });
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(api.rejectPayout).toHaveBeenCalledWith(
        "p-1",
        "Карта заблокирована",
        expect.stringMatching(/^admin-payout-reject-/),
      );
    });
  });

  it("drops the revealed number after a decision", async () => {
    api.markPaid.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
    await screen.findByText("9860 1234 5678 9015");
    fireEvent.click(screen.getByRole("button", { name: "Выплачено" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, выплачено" }));
    await waitFor(() => {
      expect(screen.queryByText("9860 1234 5678 9015")).toBeNull();
    });
  });

  it("hides the number again after a minute", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPage();
      fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
      await screen.findByText("9860 1234 5678 9015");
      act(() => {
        vi.advanceTimersByTime(61_000);
      });
      expect(screen.queryByText("9860 1234 5678 9015")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("never shows one payout's number under another payout", async () => {
    const other = {
      ...PAYOUT_DETAIL,
      request: { ...PAYOUT_DETAIL.request, id: "p-2", card_masked: "•••• 1111" },
    };
    api.getPayout.mockImplementation((id: string) =>
      Promise.resolve(id === "p-2" ? other : PAYOUT_DETAIL),
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
    await screen.findByText("9860 1234 5678 9015");
    fireEvent.click(screen.getByRole("link", { name: "next" }));
    await screen.findByText("Humo •••• 1111");
    expect(screen.queryByText("9860 1234 5678 9015")).toBeNull();
  });

  it("hides the actions when the request can no longer be decided", async () => {
    api.getPayout.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    await screen.findByText("Humo •••• 9015");
    expect(screen.queryByRole("button", { name: "Выплачено" })).toBeNull();
  });
});
