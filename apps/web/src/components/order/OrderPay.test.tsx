// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderPay } from "./OrderPay";

import type { PayProvider } from "@/lib/orders";
import type { ReactNode } from "react";

import { orderOut } from "@/test/orders";

interface Opts {
  idempotencyKey?: string;
}

const m = vi.hoisted(() => ({
  pay: vi.fn<(path: string, body: unknown, key: string | undefined) => Promise<unknown>>(),
  devPay: vi.fn<(path: string) => Promise<unknown>>(),
  balance: vi.fn<() => Promise<unknown>>(),
  providers: vi.fn<() => Promise<unknown>>(),
}));

vi.mock("@/lib/api", () => ({
  session: {
    apiPost: (path: string, body: unknown, opts?: Opts) => {
      if (path.startsWith("/api/v1/dev/orders/")) return m.devPay(path);
      if (path.endsWith("/pay")) return m.pay(path, body, opts?.idempotencyKey);
      return Promise.reject(new Error(`unexpected POST ${path}`));
    },
    apiGet: (path: string) => {
      if (path === "/api/v1/wallet") return m.balance();
      if (path === "/api/v1/payments/providers") return m.providers();
      return Promise.reject(new Error(`unexpected GET ${path}`));
    },
  },
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const KASSA = "https://kassa.example/pay?id=1";
const assign = vi.fn<(url: string) => void>();
const onPaid = vi.fn<() => void>();

const conflict = (body: Record<string, unknown>) =>
  new SessionApiError(409, "Conflict", { type: "https://x/conflict", ...body });

function setup(initial: PayProvider | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <OrderPay order={orderOut("A100")} locale="ru" initial={initial} onPaid={onPaid} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
  return client;
}

/** The pay button once the method is settled (its name carries the price). */
async function payButton(): Promise<HTMLElement> {
  const button = await screen.findByRole("button", { name: /^Оплатить 381\s000 сум$/ });
  await waitFor(() => {
    expect(button).toBeEnabled();
  });
  return button;
}

beforeEach(() => {
  for (const f of [m.pay, m.devPay, m.balance, m.providers, assign, onPaid]) f.mockReset();
  m.balance.mockResolvedValue({ balance_uzs: "0" });
  m.providers.mockResolvedValue({ providers: [{ slug: "click" }, { slug: "mock" }] });
  vi.stubGlobal("location", { pathname: "/orders/A100", search: "", hash: "", assign });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("OrderPay", () => {
  it("pays from the balance when it covers the price, then re-reads the order", async () => {
    m.balance.mockResolvedValue({ balance_uzs: "500000" });
    m.pay.mockResolvedValue({ order: orderOut("A100"), intent_url: null });
    const client = setup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Баланс/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    fireEvent.click(await payButton());
    await waitFor(() => {
      expect(onPaid).toHaveBeenCalledTimes(1);
    });
    const [path, body, key] = m.pay.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/orders/A100/pay");
    expect(body).toEqual({ provider: "wallet", locale: "ru" });
    expect(key?.length).toBeGreaterThanOrEqual(16);
    expect(assign).not.toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet", "balance"] });
  });

  it("through a kassa opens the kassa's page", async () => {
    m.pay.mockResolvedValue({ order: orderOut("A100"), intent_url: KASSA });
    setup();
    fireEvent.click(await payButton());
    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith(KASSA);
    });
    expect(m.pay.mock.calls[0]?.[1]).toEqual({ provider: "click", locale: "ru" });
    expect(onPaid).not.toHaveBeenCalled();
  });

  it("keeps the kassa chosen on the item page even when the balance covers", async () => {
    m.balance.mockResolvedValue({ balance_uzs: "500000" });
    m.providers.mockResolvedValue({ providers: [{ slug: "click" }, { slug: "payme" }] });
    m.pay.mockResolvedValue({ order: orderOut("A100"), intent_url: KASSA });
    setup("payme");
    await screen.findByRole("button", { name: /Баланс 500/ });
    expect(await screen.findByRole("button", { name: "Payme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(await payButton());
    await waitFor(() => {
      expect(m.pay).toHaveBeenCalled();
    });
    expect(m.pay.mock.calls[0]?.[1]).toEqual({ provider: "payme", locale: "ru" });
  });

  it("the test kassa pays here and never navigates away", async () => {
    m.devPay.mockResolvedValue(orderOut("A100", { status: "paid", payable: false }));
    setup("mock");
    const button = await screen.findByRole("button", { name: "Оплатить (тест)" });
    fireEvent.click(button);
    await waitFor(() => {
      expect(onPaid).toHaveBeenCalledTimes(1);
    });
    expect(m.devPay).toHaveBeenCalledWith("/api/v1/dev/orders/A100/pay");
    expect(m.pay).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("a double click pays once", async () => {
    let finish: (v: unknown) => void = () => undefined;
    m.pay.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    setup();
    const button = await payButton();
    fireEvent.click(button);
    fireEvent.click(button);
    finish({ order: orderOut("A100"), intent_url: KASSA });
    await waitFor(() => {
      expect(assign).toHaveBeenCalledTimes(1);
    });
    expect(m.pay).toHaveBeenCalledTimes(1);
  });

  it("an order paid or expired meanwhile is read again", async () => {
    m.pay.mockRejectedValue(conflict({ code: "order_not_payable", reason: "expired" }));
    setup();
    fireEvent.click(await payButton());
    await waitFor(() => {
      expect(onPaid).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a balance that fell short is read again, with no error text", async () => {
    m.balance
      .mockResolvedValueOnce({ balance_uzs: "500000" })
      .mockResolvedValue({ balance_uzs: "1000" });
    m.pay.mockRejectedValue(conflict({ code: "balance_too_low" }));
    setup();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Баланс/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    fireEvent.click(await payButton());
    expect(await screen.findByText(/^Не хватает 380\s000 сум$/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onPaid).not.toHaveBeenCalled();
  });

  it("anything else says so in our words, never the API's", async () => {
    m.pay.mockRejectedValue(new SessionApiError(500, "Internal", { detail: "db exploded" }));
    setup();
    fireEvent.click(await payButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Что-то пошло не так. Попробуйте ещё раз.",
    );
    expect(screen.queryByText(/exploded/)).toBeNull();
    expect(onPaid).not.toHaveBeenCalled();
  });
});
