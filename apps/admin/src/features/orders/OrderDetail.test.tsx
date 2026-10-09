import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type AdminOrderDetail } from "./api";
import { ATTENTION, DETAIL, LISSKINS, RESOLVED, SKINSLINK } from "./fixtures";
import { detailKey } from "./keys";
import { OrderDetail } from "./OrderDetail";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  listOrders: vi.fn(),
  getOrder: vi.fn(),
  resolveOrder: vi.fn(),
  refundOrder: vi.fn(),
  retryOrder: vi.fn(),
}));
vi.mock("./api", () => api);

function renderDetail(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/orders/O7K2M9QX"]}>
        <Routes>
          <Route path="/orders/:number" element={<OrderDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return qc;
}

function conflict(code: string): ApiError {
  return new ApiError(409, "Conflict", { code, detail: "English detail" });
}

describe("OrderDetail", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getOrder.mockResolvedValue(DETAIL);
  });

  it.each([
    ["trade_hold", "задержка обменов Steam"],
    ["price_moved", "цена поставщика выросла"],
  ] as const)("names the %s failure reason, never «undefined»", async (reason, label) => {
    api.getOrder.mockResolvedValue({
      ...DETAIL,
      order: {
        ...DETAIL.order,
        status: "failed",
        failed_at: "2026-09-30T10:06:00Z",
        failure_reason: reason,
      },
    });
    renderDetail();
    const order = await screen.findByRole("region", { name: "Заказ" });
    expect(within(order).getByText(new RegExp(label))).toBeInTheDocument();
    expect(order).not.toHaveTextContent("undefined");
  });

  it("shows the order's fields, money, payments and buyer", async () => {
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Заказ O7K2M9QX" })).toBeInTheDocument();
    expect(api.getOrder).toHaveBeenCalledWith("O7K2M9QX");
    const order = screen.getByRole("region", { name: "Заказ" });
    expect(within(order).getByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
    expect(within(order).getByTestId("order-status")).toHaveTextContent("покупаем");
    expect(within(order).getByText(/171\s800 сум/)).toBeInTheDocument();
    expect(within(order).getByText("$13.500000")).toBeInTheDocument();
    expect(within(order).getByText("$13.580000")).toBeInTheDocument();
    expect(within(order).getByText("$0.380000")).toBeInTheDocument();
    expect(within(order).getByText("12650.5000")).toBeInTheDocument();
    expect(within(order).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");

    const payments = screen.getByRole("region", { name: "Платежи" });
    expect(within(payments).getByRole("link", { name: /Click/ })).toHaveAttribute(
      "href",
      "/payments/p-1",
    );
    expect(within(payments).getByText("оплачен")).toBeInTheDocument();
  });

  it("names the order's source and offer", async () => {
    renderDetail();
    const order = await screen.findByRole("region", { name: "Заказ" });
    expect(within(order).getByText("Waxpeer · wx:4242")).toBeInTheDocument();
  });

  it("names a Skinslink order's source and shows its purchase", async () => {
    api.getOrder.mockResolvedValue({
      ...DETAIL,
      order: { ...DETAIL.order, source: "skinslink", offer_id: "sl:380", listing_id: null },
      trade: null,
      skinslink: SKINSLINK,
    });
    renderDetail();
    const order = await screen.findByRole("region", { name: "Заказ" });
    expect(within(order).getByText("Skinslink · sl:380")).toBeInTheDocument();
    const purchase = screen.getByRole("region", { name: "Покупка Skinslink" });
    expect(within(purchase).getByText("178")).toBeInTheDocument();
    expect(within(purchase).getByText("active")).toBeInTheDocument();
    expect(within(purchase).getByText("$12.000000")).toBeInTheDocument();
    expect(within(purchase).getByRole("link", { name: "6912345678" })).toHaveAttribute(
      "href",
      "https://steamcommunity.com/tradeoffer/6912345678/",
    );
    expect(within(purchase).getByText("откат после получения")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Обмен" })).toBeNull();
  });

  it("names a LIS-SKINS order's source and shows its purchase", async () => {
    api.getOrder.mockResolvedValue({
      ...DETAIL,
      order: { ...DETAIL.order, source: "lisskins", offer_id: "ls:125345", listing_id: null },
      trade: null,
      lisskins: LISSKINS,
    });
    renderDetail();
    const order = await screen.findByRole("region", { name: "Заказ" });
    expect(within(order).getByText("LIS-SKINS · ls:125345")).toBeInTheDocument();
    const purchase = screen.getByRole("region", { name: "Покупка LIS-SKINS" });
    expect(within(purchase).getByText("55")).toBeInTheDocument();
    expect(within(purchase).getByText("wait_accept")).toBeInTheDocument();
    expect(within(purchase).getByText("$12.340000")).toBeInTheDocument();
    expect(within(purchase).getByRole("link", { name: "7252638866" })).toHaveAttribute(
      "href",
      "https://steamcommunity.com/tradeoffer/7252638866/",
    );
    expect(within(purchase).getByText("откат после получения")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Обмен" })).toBeNull();
  });

  it("offers «Разобрано» for a purchase's open attention", async () => {
    api.getOrder.mockResolvedValue({
      ...DETAIL,
      order: { ...DETAIL.order, source: "lisskins", offer_id: "ls:125345", listing_id: null },
      trade: null,
      lisskins: LISSKINS,
      can_refund: false,
      can_retry: false,
    });
    renderDetail();
    expect(await screen.findByRole("button", { name: "Разобрано" })).toBeInTheDocument();
  });

  it("renders the trade block and never a trade-link token", async () => {
    renderDetail();
    const trade = await screen.findByRole("region", { name: "Обмен" });
    expect(within(trade).getByText("4 — предложение отправлено")).toBeInTheDocument();
    expect(within(trade).getByRole("link", { name: "7000000001" })).toHaveAttribute(
      "href",
      "https://steamcommunity.com/tradeoffer/7000000001/",
    );
    expect(within(trade).getByText("60000009")).toBeInTheDocument();
    expect(within(trade).getByText("6f1c2a52-0000-4000-8000-000000000001")).toBeInTheDocument();
    expect(within(trade).getByText(/SellerName/)).toBeInTheDocument();
    expect(within(trade).getByText("seller_cancelled")).toBeInTheDocument();
    // Whatever token text is on the page is the masked one.
    const text = document.body.textContent;
    expect(text).toContain("token=••••XY");
    expect(text).not.toMatch(/token=(?!••••)/);
  });

  it("copies the project id and the Waxpeer id", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Скопировать project id" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("6f1c2a52-0000-4000-8000-000000000001");
    });
    fireEvent.click(screen.getByRole("button", { name: "Скопировать id Waxpeer" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("60000009");
    });
  });

  it("says there is no trade yet for an unbought order", async () => {
    api.getOrder.mockResolvedValue({ ...DETAIL, trade: null });
    renderDetail();
    const trade = await screen.findByRole("region", { name: "Обмен" });
    expect(trade).toHaveTextContent("Покупки в Waxpeer ещё не было.");
  });

  it("shows no money action when the API says neither is possible", async () => {
    renderDetail();
    await screen.findByRole("region", { name: "Обмен" });
    expect(screen.queryByRole("button", { name: "Вернуть деньги на баланс" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Повторить покупку" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Разобрано" })).toBeNull();
  });

  it("offers each money action only on its own flag", async () => {
    api.getOrder.mockResolvedValue({ ...RESOLVED, can_refund: false });
    renderDetail();
    expect(await screen.findByRole("button", { name: "Повторить покупку" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Вернуть деньги на баланс" })).toBeNull();
  });

  it("offers the refund alone when a retry is not possible", async () => {
    api.getOrder.mockResolvedValue({ ...RESOLVED, can_retry: false });
    renderDetail();
    expect(
      await screen.findByRole("button", { name: "Вернуть деньги на баланс" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Повторить покупку" })).toBeNull();
  });

  it("names the attention reason", async () => {
    api.getOrder.mockResolvedValue(ATTENTION);
    renderDetail();
    expect((await screen.findAllByText(/несколько обменов/)).length).toBeGreaterThan(0);
  });

  describe("refund", () => {
    beforeEach(() => {
      api.getOrder.mockResolvedValue(RESOLVED);
    });

    it("confirms with the amount, then sends one request with one key", async () => {
      const after: AdminOrderDetail = {
        ...RESOLVED,
        order: { ...RESOLVED.order, status: "failed", refunded_to: "balance" },
        can_refund: false,
        can_retry: false,
      };
      api.refundOrder.mockResolvedValue(after);
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Вернуть деньги на баланс" }));
      expect(api.refundOrder).not.toHaveBeenCalled();
      const confirm = screen.getByTestId("order-confirm");
      expect(confirm).toHaveTextContent(/Вернуть 171\s800 сум на баланс покупателя\?/);
      fireEvent.click(within(confirm).getByRole("button", { name: "Вернуть" }));
      await waitFor(() => {
        expect(api.refundOrder).toHaveBeenCalledTimes(1);
      });
      const [number, key] = api.refundOrder.mock.calls[0] as [string, string];
      expect(number).toBe("O7K2M9QX");
      expect(key.length).toBeGreaterThanOrEqual(16);
      // The page now shows the new state: no more money actions.
      await waitFor(() => {
        expect(screen.queryByRole("button", { name: "Вернуть деньги на баланс" })).toBeNull();
      });
      expect(screen.getByTestId("order-status")).toHaveTextContent("не получилось");
    });

    it("a double click on «Вернуть» sends one request", async () => {
      let finish: (d: AdminOrderDetail) => void = () => undefined;
      api.refundOrder.mockReturnValue(
        new Promise<AdminOrderDetail>((resolve) => {
          finish = resolve;
        }),
      );
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Вернуть деньги на баланс" }));
      const confirm = within(screen.getByTestId("order-confirm")).getByRole("button", {
        name: "Вернуть",
      });
      fireEvent.click(confirm);
      fireEvent.click(confirm);
      finish({ ...RESOLVED, can_refund: false, can_retry: false });
      await waitFor(() => {
        expect(screen.queryByTestId("order-confirm")).toBeNull();
      });
      expect(api.refundOrder).toHaveBeenCalledTimes(1);
    });

    it("closes an open confirm once a refetch says the refund is no longer possible", async () => {
      const qc = renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Вернуть деньги на баланс" }));
      expect(screen.getByTestId("order-confirm")).toBeInTheDocument();
      act(() => {
        qc.setQueryData(detailKey("O7K2M9QX"), { ...RESOLVED, can_refund: false });
      });
      await waitFor(() => {
        expect(screen.queryByTestId("order-confirm")).toBeNull();
      });
      expect(screen.queryByRole("button", { name: "Вернуть" })).toBeNull();
      expect(api.refundOrder).not.toHaveBeenCalled();
    });

    it("sends nothing when the confirm is cancelled", async () => {
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Вернуть деньги на баланс" }));
      fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
      expect(screen.queryByTestId("order-confirm")).toBeNull();
      expect(api.refundOrder).not.toHaveBeenCalled();
    });

    it("keeps the same key when a failed submission is repeated", async () => {
      api.refundOrder.mockRejectedValueOnce(new ApiError(500, "x", null));
      api.refundOrder.mockResolvedValue({ ...RESOLVED, can_refund: false });
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Вернуть деньги на баланс" }));
      fireEvent.click(screen.getByRole("button", { name: "Вернуть" }));
      await screen.findByRole("alert");
      fireEvent.click(screen.getByRole("button", { name: "Вернуть" }));
      await waitFor(() => {
        expect(api.refundOrder).toHaveBeenCalledTimes(2);
      });
      expect(api.refundOrder.mock.calls[0]?.[1]).toBe(api.refundOrder.mock.calls[1]?.[1]);
    });

    it.each([
      ["order_in_flight", "Скин ещё в пути — вернуть деньги нельзя."],
      ["already_refunded", "Деньги уже на балансе."],
      ["order_not_refundable", "Этот заказ нельзя вернуть."],
      ["order_busy", "Покупка ещё идёт — попробуйте через минуту."],
      ["order_needs_attention", "Сначала разберите обмен."],
      ["waxpeer_unavailable", "Не удалось проверить покупку — попробуйте позже."],
      [
        "idempotency_mismatch",
        "Эта операция уже была выполнена с другими данными. Обновите страницу.",
      ],
    ])("answers %s in Russian and refetches the order", async (code, text) => {
      api.refundOrder.mockRejectedValue(conflict(code));
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Вернуть деньги на баланс" }));
      fireEvent.click(screen.getByRole("button", { name: "Вернуть" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(text);
      expect(screen.getByRole("alert")).not.toHaveTextContent("English detail");
      await waitFor(() => {
        expect(api.getOrder.mock.calls.length).toBeGreaterThan(1);
      });
    });
  });

  describe("retry", () => {
    beforeEach(() => {
      api.getOrder.mockResolvedValue(RESOLVED);
    });

    it("warns about the Waxpeer cabinet before the one request", async () => {
      api.retryOrder.mockResolvedValue({ ...RESOLVED, can_retry: false, can_refund: false });
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Повторить покупку" }));
      const confirm = screen.getByTestId("order-confirm");
      expect(confirm).toHaveTextContent(
        "Сначала проверьте project id в кабинете Waxpeer — повтор купит скин, если покупки там нет",
      );
      expect(api.retryOrder).not.toHaveBeenCalled();
      fireEvent.click(within(confirm).getByRole("button", { name: "Повторить" }));
      await waitFor(() => {
        expect(api.retryOrder).toHaveBeenCalledTimes(1);
      });
      expect(api.retryOrder.mock.calls[0]?.[0]).toBe("O7K2M9QX");
    });

    it("a second deliberate retry after a success gets a new key", async () => {
      api.retryOrder.mockResolvedValue(RESOLVED); // still retryable: the page offers it again
      renderDetail();
      for (let i = 0; i < 2; i += 1) {
        fireEvent.click(await screen.findByRole("button", { name: "Повторить покупку" }));
        fireEvent.click(
          within(screen.getByTestId("order-confirm")).getByRole("button", { name: "Повторить" }),
        );
        await waitFor(() => {
          expect(api.retryOrder).toHaveBeenCalledTimes(i + 1);
        });
        await waitFor(() => {
          expect(screen.queryByTestId("order-confirm")).toBeNull();
        });
      }
      const [first, second] = api.retryOrder.mock.calls.map((c) => c[1] as string);
      expect(first).not.toBe(second);
    });

    it("answers not_retryable in Russian", async () => {
      api.retryOrder.mockRejectedValue(conflict("not_retryable"));
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Повторить покупку" }));
      fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Повтор сейчас невозможен.");
    });
  });

  describe("resolve", () => {
    beforeEach(() => {
      api.getOrder.mockResolvedValue(ATTENTION);
    });

    it("sends the trimmed note with one key", async () => {
      api.resolveOrder.mockResolvedValue(RESOLVED);
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Разобрано" }));
      fireEvent.change(screen.getByLabelText("Заметка"), {
        target: { value: "  проверил в кабинете " },
      });
      fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
      await waitFor(() => {
        expect(api.resolveOrder).toHaveBeenCalledTimes(1);
      });
      const [number, note, key] = api.resolveOrder.mock.calls[0] as [string, string, string];
      expect(number).toBe("O7K2M9QX");
      expect(note).toBe("проверил в кабинете");
      expect(key.length).toBeGreaterThanOrEqual(16);
      // The refund and retry buttons appear once the API says they are possible.
      expect(
        await screen.findByRole("button", { name: "Вернуть деньги на баланс" }),
      ).toBeInTheDocument();
    });

    it("sends a null note when none is typed and caps the note at 500", async () => {
      api.resolveOrder.mockResolvedValue(RESOLVED);
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Разобрано" }));
      expect(screen.getByLabelText("Заметка")).toHaveAttribute("maxLength", "500");
      fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
      await waitFor(() => {
        expect(api.resolveOrder).toHaveBeenCalledTimes(1);
      });
      expect(api.resolveOrder.mock.calls[0]?.[1]).toBeNull();
    });

    it("answers nothing_to_resolve in Russian", async () => {
      api.resolveOrder.mockRejectedValue(conflict("nothing_to_resolve"));
      renderDetail();
      fireEvent.click(await screen.findByRole("button", { name: "Разобрано" }));
      fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Здесь нечего разбирать.");
    });
  });

  it("says when the order is missing", async () => {
    api.getOrder.mockRejectedValue(new ApiError(404, "Not Found", null));
    renderDetail();
    expect(await screen.findByText("Заказ не найден.")).toBeInTheDocument();
  });
});
