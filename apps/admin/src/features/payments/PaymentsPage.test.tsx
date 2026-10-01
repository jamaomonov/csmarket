import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ROW } from "./fixtures";
import { PAYMENT_STATUSES } from "./kinds";
import { PaymentsPage } from "./PaymentsPage";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({ listPayments: vi.fn(), getPayment: vi.fn() }));
vi.mock("./api", () => api);

function renderPage(url = "/payments") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <PaymentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PaymentsPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
  });

  it("lists payments with amount, kassa, status chip and user link", async () => {
    api.listPayments.mockResolvedValue({ items: [ROW], next_cursor: null });
    renderPage();
    const link = await screen.findByRole("link", { name: "P100001" });
    expect(link).toHaveAttribute("href", "/payments/p-1");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText(/50\s000 сум/)).toBeInTheDocument();
    expect(within(row).getByText("Click")).toBeInTheDocument();
    expect(within(row).getByTestId("payment-status")).toHaveTextContent("оплачен");
    expect(within(row).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");
    expect(api.listPayments).toHaveBeenCalledWith({});
  });

  it("shows the chip text for every status", async () => {
    api.listPayments.mockResolvedValue({
      items: PAYMENT_STATUSES.map((status, i) => ({
        ...ROW,
        id: `p-${String(i)}`,
        number: `P${String(i)}`,
        status,
      })),
      next_cursor: null,
    });
    renderPage();
    await screen.findByTestId("payments-table");
    const chips = screen.getAllByTestId("payment-status").map((c) => c.textContent);
    expect(chips).toEqual(["создан", "ждёт кассу", "оплачен", "не прошёл", "отменён", "возвращён"]);
  });

  it("passes the typed number as q and keeps it in the URL", async () => {
    api.listPayments.mockResolvedValue({ items: [ROW], next_cursor: null });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Номер платежа или пополнения"), {
      target: { value: "  t100 " },
    });
    await waitFor(() => {
      expect(api.listPayments).toHaveBeenCalledWith({ q: "t100" });
    });
  });

  it("starts from ?q= so the user card's top-up links work", async () => {
    api.listPayments.mockResolvedValue({ items: [ROW], next_cursor: null });
    renderPage("/payments?q=T100001");
    expect(await screen.findByLabelText("Номер платежа или пополнения")).toHaveValue("T100001");
    expect(api.listPayments).toHaveBeenCalledTimes(1);
    expect(api.listPayments).toHaveBeenCalledWith({ q: "T100001" });
  });

  it("filters by status, kassa and purpose", async () => {
    api.listPayments.mockResolvedValue({ items: [ROW], next_cursor: null });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Статус"), { target: { value: "failed" } });
    await waitFor(() => {
      expect(api.listPayments).toHaveBeenLastCalledWith({ status: "failed" });
    });
    fireEvent.change(screen.getByLabelText("Касса"), { target: { value: "payme" } });
    await waitFor(() => {
      expect(api.listPayments).toHaveBeenLastCalledWith({ status: "failed", provider: "payme" });
    });
    fireEvent.change(screen.getByLabelText("Назначение"), { target: { value: "topup" } });
    await waitFor(() => {
      expect(api.listPayments).toHaveBeenLastCalledWith({
        status: "failed",
        provider: "payme",
        purpose: "topup",
      });
    });
  });

  it("ignores an unknown status in the URL", async () => {
    api.listPayments.mockResolvedValue({ items: [ROW], next_cursor: null });
    renderPage("/payments?status=bogus");
    await screen.findByTestId("payments-table");
    expect(api.listPayments).toHaveBeenCalledWith({});
  });

  it("ignores a ?q= longer than the API accepts", async () => {
    api.listPayments.mockResolvedValue({ items: [ROW], next_cursor: null });
    renderPage(`/payments?q=${"T".repeat(33)}`);
    await screen.findByTestId("payments-table");
    expect(screen.getByLabelText("Номер платежа или пополнения")).toHaveValue("");
    expect(api.listPayments).toHaveBeenCalledWith({});
  });

  it("shows a Russian line, not the raw detail, when the API refuses a filter", async () => {
    api.listPayments.mockRejectedValue(
      new ApiError(422, "Unprocessable Entity", { detail: [{ msg: "String should match" }] }),
    );
    renderPage("/payments?q=T7K");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Запрос не принят: проверьте введённые значения.",
    );
  });

  it("loads the next page behind «Показать ещё»", async () => {
    api.listPayments
      .mockResolvedValueOnce({ items: [ROW], next_cursor: "c-2" })
      .mockResolvedValueOnce({
        items: [{ ...ROW, id: "p-9", number: "P900009" }],
        next_cursor: null,
      });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByRole("link", { name: "P900009" })).toBeInTheDocument();
    expect(api.listPayments).toHaveBeenLastCalledWith({ cursor: "c-2" });
  });

  it("says when nothing matches", async () => {
    api.listPayments.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();
    expect(await screen.findByText("Ничего не нашли.")).toBeInTheDocument();
  });
});
