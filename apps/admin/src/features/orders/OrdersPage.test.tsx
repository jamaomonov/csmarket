import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ORDER_ROW } from "./fixtures";
import { ORDER_STATUSES } from "./kinds";
import { OrdersPage } from "./OrdersPage";

const api = vi.hoisted(() => ({ listOrders: vi.fn(), getOrder: vi.fn() }));
vi.mock("./api", () => api);

function renderPage(url = "/orders") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <OrdersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OrdersPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
  });

  it("lists orders with skin, price, payment, status chip, user link and date", async () => {
    api.listOrders.mockResolvedValue({ items: [ORDER_ROW], next_cursor: null });
    renderPage();
    const link = await screen.findByRole("link", { name: "O7K2M9QX" });
    expect(link).toHaveAttribute("href", "/orders/O7K2M9QX");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
    expect(within(row).getByText(/171\s800 сум/)).toBeInTheDocument();
    expect(within(row).getByText("Click")).toBeInTheDocument();
    expect(within(row).getByTestId("order-status")).toHaveTextContent("покупаем");
    expect(within(row).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");
    expect(within(row).queryByTestId("order-attention")).toBeNull();
    expect(api.listOrders).toHaveBeenCalledWith({});
  });

  it("says the chip word for every status", async () => {
    api.listOrders.mockResolvedValue({
      items: ORDER_STATUSES.map((status, i) => ({
        ...ORDER_ROW,
        number: `O${String(i)}`,
        status,
      })),
      next_cursor: null,
    });
    renderPage();
    await screen.findByTestId("orders-table");
    expect(screen.getAllByTestId("order-status").map((c) => c.textContent)).toEqual([
      "ждёт оплаты",
      "оплачен",
      "покупаем",
      "обмен отправлен",
      "получен",
      "отменён",
      "не получилось",
      "обмен не состоялся",
    ]);
  });

  it("badges an order that needs attention, with the reason", async () => {
    api.listOrders.mockResolvedValue({
      items: [{ ...ORDER_ROW, attention_reason: "source_forbidden" }],
      next_cursor: null,
    });
    renderPage();
    const badge = await screen.findByTestId("order-attention");
    expect(badge).toHaveTextContent("внимание");
    expect(badge).toHaveTextContent("Площадка: IP не в белом списке");
  });

  it("starts from ?q= and passes it to the API", async () => {
    api.listOrders.mockResolvedValue({ items: [ORDER_ROW], next_cursor: null });
    renderPage("/orders?q=redline");
    expect(await screen.findByLabelText("Номер заказа или название")).toHaveValue("redline");
    expect(api.listOrders).toHaveBeenCalledTimes(1);
    expect(api.listOrders).toHaveBeenCalledWith({ q: "redline" });
  });

  it("passes the typed text trimmed as q", async () => {
    api.listOrders.mockResolvedValue({ items: [ORDER_ROW], next_cursor: null });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Номер заказа или название"), {
      target: { value: "  o7k " },
    });
    await waitFor(() => {
      expect(api.listOrders).toHaveBeenCalledWith({ q: "o7k" });
    });
  });

  it("filters by status and drops an unknown status or an over-long q from the URL", async () => {
    api.listOrders.mockResolvedValue({ items: [ORDER_ROW], next_cursor: null });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Статус"), { target: { value: "failed" } });
    await waitFor(() => {
      expect(api.listOrders).toHaveBeenCalledWith({ status: "failed" });
    });
  });

  it("ignores hand-edited filter values", async () => {
    api.listOrders.mockResolvedValue({ items: [], next_cursor: null });
    renderPage(`/orders?status=bogus&q=${"x".repeat(101)}`);
    await screen.findByText("Ничего не нашли.");
    expect(api.listOrders).toHaveBeenCalledWith({});
  });

  it("loads the next page on «Показать ещё»", async () => {
    api.listOrders
      .mockResolvedValueOnce({ items: [ORDER_ROW], next_cursor: "c2" })
      .mockResolvedValueOnce({
        items: [{ ...ORDER_ROW, number: "O2" }],
        next_cursor: null,
      });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByRole("link", { name: "O2" })).toBeInTheDocument();
    expect(api.listOrders).toHaveBeenLastCalledWith({ cursor: "c2" });
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });

  it("shows an error", async () => {
    api.listOrders.mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Не получилось");
  });
});
