// @vitest-environment jsdom
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OrderOut } from "@/lib/orders";
import type { ReactNode } from "react";

import { orderState as state, renderOrderView, tick } from "@/test/order-view";
import { orderOut } from "@/test/orders";

interface Opts {
  idempotencyKey?: string;
}

const m = vi.hoisted(() => ({
  auth: { value: {} },
  get: vi.fn<(path: string) => Promise<OrderOut>>(),
  pay: vi.fn<(path: string, body: unknown, key: string | undefined) => Promise<unknown>>(),
  devPay: vi.fn<(path: string) => Promise<unknown>>(),
}));

vi.mock("@/lib/api", () => ({
  session: {
    apiPost: (path: string, body: unknown, opts?: Opts) => {
      if (path.startsWith("/api/v1/dev/orders/")) return m.devPay(path);
      if (path.endsWith("/pay")) return m.pay(path, body, opts?.idempotencyKey);
      return Promise.reject(new Error(`unexpected POST ${path}`));
    },
    apiGet: (path: string) => {
      if (path.startsWith("/api/v1/orders/")) return m.get(path);
      if (path === "/api/v1/wallet") return Promise.resolve({ balance_uzs: "0" });
      if (path === "/api/v1/payments/providers") {
        return Promise.resolve({ providers: [{ slug: "click" }, { slug: "mock" }] });
      }
      return Promise.reject(new Error(`unexpected GET ${path}`));
    },
  },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => m.auth.value }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const KASSA = "https://kassa.example/pay?id=1";
const assign = vi.fn<(url: string) => void>();
let seq = 0;
let number = "A1";

function at(search: string): void {
  vi.stubGlobal("location", { pathname: `/orders/${number}`, search, hash: "", assign });
}

const view = () => renderOrderView(number);

beforeEach(() => {
  seq += 1;
  number = `A${seq.toString()}`; // the once-per-tab kassa mark is per number
  m.auth.value = {
    status: "signed_in",
    user: { id: "u1" },
    signInHref: (l: string) => `/s?l=${l}`,
  };
  for (const f of [m.get, m.pay, m.devPay, assign]) f.mockReset();
  at("");
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
describe("OrderView — paying", () => {
  it("a pending order shows the skin, its price and the way to pay", async () => {
    m.get.mockResolvedValue(orderOut(number, { phase: "Phase 2" }));
    view();
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ #${number}` }),
    ).toBeInTheDocument();
    expect(state()).toBe("pending");
    expect(screen.getByText("Ждёт оплаты")).toBeInTheDocument();
    // The weapon above, the skin's own name (a link to it) below, the wear as a chip.
    expect(screen.getByText("AK-47")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Redline" })).toHaveAttribute(
      "href",
      "/item/ak-47-redline-field-tested",
    );
    expect(screen.getByText("После полевых испытаний")).toBeInTheDocument();
    expect(screen.getByText("Phase 2")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /^Оплатить 381\s000 сум$/ })).toBeVisible();
    expect(m.get).toHaveBeenCalledWith(`/api/v1/orders/${number}`);
    expect(m.pay).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("with ?go=1 opens the chosen kassa once, strips the flag and never again in this tab", async () => {
    const replace = vi.spyOn(window.history, "replaceState");
    at("?go=1&via=click");
    m.get.mockResolvedValue(orderOut(number));
    m.pay.mockResolvedValue({ order: orderOut(number), intent_url: KASSA });
    const first = view();
    await screen.findByRole("heading", { level: 1 });
    await vi.waitFor(() => {
      expect(assign).toHaveBeenCalledWith(KASSA);
    });
    expect(m.pay).toHaveBeenCalledTimes(1);
    const [path, body, key] = m.pay.mock.calls[0] ?? [];
    expect(path).toBe(`/api/v1/orders/${number}/pay`);
    expect(body).toEqual({ provider: "click", locale: "ru" });
    expect(key?.length).toBeGreaterThanOrEqual(16);
    expect(replace).toHaveBeenCalledWith(null, "", `/orders/${number}?via=click`);
    await act(() => first.client.refetchQueries());
    first.unmount();
    // A reload that still carries the flag (the strip never landed).
    view();
    await screen.findByRole("heading", { level: 1 });
    expect(assign).toHaveBeenCalledTimes(1);
    expect(m.pay).toHaveBeenCalledTimes(1);
  });

  it("opens nothing once the buyer has left the page", async () => {
    at("?go=1&via=click");
    m.get.mockResolvedValue(orderOut(number));
    let answer: (v: unknown) => void = () => undefined;
    m.pay.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    const { unmount } = view();
    await screen.findByRole("heading", { level: 1 });
    await vi.waitFor(() => {
      expect(m.pay).toHaveBeenCalledTimes(1);
    });
    unmount();
    await act(async () => {
      answer({ order: orderOut(number), intent_url: KASSA });
      await Promise.resolve();
    });
    expect(assign).not.toHaveBeenCalled();
  });

  it("opens nothing when the answer comes too late to be part of the tap", async () => {
    vi.useFakeTimers();
    at("?go=1&via=click");
    m.get.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => {
            resolve(orderOut(number));
          }, 9_000);
        }),
    );
    view();
    await tick(9_000);
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(m.pay).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("opens nothing for an order already paid", async () => {
    at("?go=1&via=click");
    m.get.mockResolvedValue(orderOut(number, { status: "buying", payable: false }));
    view();
    await screen.findByRole("heading", { level: 1 });
    expect(state()).toBe("buying");
    expect(m.pay).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it.each([["?go=1&via=mock"], ["?mock=1"]])(
    "the test kassa (%s) pays from the page, never navigates, then the order is read again",
    async (search) => {
      at(search);
      m.get
        .mockResolvedValueOnce(orderOut(number))
        .mockResolvedValue(orderOut(number, { status: "paid", payable: false }));
      m.devPay.mockResolvedValue(orderOut(number, { status: "paid", payable: false }));
      view();
      const pay = await screen.findByRole("button", { name: "Оплатить (тест)" });
      expect(m.pay).not.toHaveBeenCalled();
      expect(assign).not.toHaveBeenCalled();
      fireEvent.click(pay);
      await vi.waitFor(() => {
        expect(state()).toBe("paid");
      });
      expect(m.devPay).toHaveBeenCalledWith(`/api/v1/dev/orders/${number}/pay`);
      expect(screen.getByText("Покупаем скин — обмен придёт в Steam через минуту.")).toBeVisible();
      expect(assign).not.toHaveBeenCalled();
    },
  );

  it("an order past its time to pay says so and offers nothing to pay", async () => {
    at("?go=1&via=click");
    m.get.mockResolvedValue(orderOut(number, { payable: false }));
    view();
    expect(await screen.findByText("Время на оплату вышло.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Оплатить/ })).toBeNull();
    expect(m.pay).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("an order that was never paid and was cancelled reads as time run out", async () => {
    m.get.mockResolvedValue(
      orderOut(number, { status: "cancelled", payable: false, paid_at: null }),
    );
    view();
    expect(await screen.findByText("Время на оплату вышло.")).toBeInTheDocument();
    expect(state()).toBe("cancelled");
    expect(screen.queryByText("Заказ отменён.")).toBeNull();
    expect(screen.queryByRole("button", { name: /Оплатить/ })).toBeNull();
  });

  it("a cancelled order that had been paid says it was cancelled", async () => {
    m.get.mockResolvedValue(
      orderOut(number, {
        status: "cancelled",
        payable: false,
        paid_at: "2026-10-02T10:05:00Z",
      }),
    );
    view();
    expect(await screen.findByText("Заказ отменён.")).toBeInTheDocument();
    expect(state()).toBe("cancelled");
    expect(screen.queryByRole("button", { name: /Оплатить/ })).toBeNull();
    expect(screen.queryByText("Обмен в Steam")).toBeNull();
  });
});
