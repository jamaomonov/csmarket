import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DETAIL, RAW_PHONE } from "./fixtures";
import { PaymentDetail } from "./PaymentDetail";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({ listPayments: vi.fn(), getPayment: vi.fn() }));
vi.mock("./api", () => api);

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/payments/p-1"]}>
        <Routes>
          <Route path="/payments/:id" element={<PaymentDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PaymentDetail", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
  });

  it("shows the payment, its top-up and the kassa rows", async () => {
    api.getPayment.mockResolvedValue(DETAIL);
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Платёж P100001" })).toBeInTheDocument();
    const payment = screen.getByRole("region", { name: "Платёж" });
    expect(within(payment).getByText("ref-77")).toBeInTheDocument();
    expect(within(payment).getByTestId("payment-status")).toHaveTextContent("оплачен");
    expect(within(payment).getByRole("link", { name: "Ivan" })).toHaveAttribute(
      "href",
      "/users/u-1",
    );

    const topup = screen.getByRole("region", { name: "Пополнение" });
    expect(within(topup).getByText("T100001")).toBeInTheDocument();
    expect(within(topup).getByText("зачислено")).toBeInTheDocument();

    const rows = within(screen.getByTestId("kassa-table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const [payme, uzum] = rows as [HTMLElement, HTMLElement];
    expect(within(payme).getByText("Payme")).toBeInTheDocument();
    expect(within(payme).getByText("payme-abc")).toBeInTheDocument();
    expect(within(payme).getByText("проведена")).toBeInTheDocument();
    // Tiyin keeps its unit and is never converted.
    expect(within(payme).getByText(/5\s000\s000\sтийин/)).toBeInTheDocument();
    expect(within(uzum).getByText(/50\s000 сум/)).toBeInTheDocument();
    expect(within(uzum).getByText("подтверждён")).toBeInTheDocument();
  });

  it("links the order a payment pays for", async () => {
    api.getPayment.mockResolvedValue({
      ...DETAIL,
      topup: null,
      order: { number: "O7K2M9QX", status: "buying", price_uzs: "171800" },
    });
    renderDetail();
    const order = await screen.findByRole("region", { name: "Заказ" });
    expect(within(order).getByRole("link", { name: "O7K2M9QX" })).toHaveAttribute(
      "href",
      "/orders/O7K2M9QX",
    );
    expect(within(order).getByText(/171\s800 сум/)).toBeInTheDocument();
    expect(within(order).getByTestId("order-status")).toHaveTextContent("покупаем");
    expect(screen.queryByRole("region", { name: "Пополнение" })).toBeNull();
  });

  it("shows no order block for a top-up payment", async () => {
    api.getPayment.mockResolvedValue(DETAIL);
    renderDetail();
    await screen.findByRole("region", { name: "Пополнение" });
    expect(screen.queryByRole("region", { name: "Заказ" })).toBeNull();
  });

  it("renders only the allow-listed extra keys and never the raw phone", async () => {
    api.getPayment.mockResolvedValue(DETAIL);
    const { container } = (renderDetail(), { container: document.body });
    await screen.findByTestId("kassa-table");
    expect(screen.getByText("+998••••••67")).toBeInTheDocument();
    expect(screen.getByText("uzum_bank")).toBeInTheDocument();
    expect(container.textContent).not.toContain(RAW_PHONE);
    expect(container.textContent).not.toContain("901234567");
  });

  it("hides an unmasked phone even if the API ever sends one in the phone key", async () => {
    const [first, second] = DETAIL.kassa;
    api.getPayment.mockResolvedValue({
      ...DETAIL,
      kassa: [first, { ...second, extra: { phone: `+${RAW_PHONE}` } }],
    });
    renderDetail();
    await screen.findByTestId("kassa-table");
    expect(document.body.textContent).not.toContain(RAW_PHONE);
    expect(screen.getByText("скрыт")).toBeInTheDocument();
  });

  it("omits the top-up block for an order payment and says when the kassa has not called", async () => {
    api.getPayment.mockResolvedValue({
      ...DETAIL,
      payment: { ...DETAIL.payment, purpose: "order", status: "created" },
      topup: null,
      kassa: [],
    });
    renderDetail();
    expect(await screen.findByText("Касса ещё не обращалась.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Пополнение" })).not.toBeInTheDocument();
  });

  it("says when the payment does not exist", async () => {
    api.getPayment.mockRejectedValue(new ApiError(404, "Not Found", "{}"));
    renderDetail();
    expect(await screen.findByText("Платёж не найден.")).toBeInTheDocument();
  });
});
