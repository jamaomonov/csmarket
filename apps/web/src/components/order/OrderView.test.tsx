// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderView } from "./OrderView";

import type { OrderOut } from "@/lib/orders";
import type { ReactNode } from "react";

import { orderOut, tradeOut } from "@/test/orders";

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

function view() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <OrderView locale="ru" number={number} />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  return { ...render(tree), client };
}

const state = () => screen.getByTestId("order-status").getAttribute("data-state");

/** Run `ms` of fake time, plus the 0 ms timers a query's answer rides on. */
async function tick(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms + 20);
  });
}

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
    expect(screen.getByRole("link", { name: "AK-47 | Redline (Field-Tested)" })).toHaveAttribute(
      "href",
      "/item/ak-47-redline-field-tested",
    );
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

  it("a cancelled order says so", async () => {
    m.get.mockResolvedValue(orderOut(number, { status: "cancelled", payable: false }));
    view();
    expect(await screen.findByText("Заказ отменён.")).toBeInTheDocument();
    expect(state()).toBe("cancelled");
    expect(screen.queryByRole("button", { name: /Оплатить/ })).toBeNull();
    expect(screen.queryByText("Обмен в Steam")).toBeNull();
  });
});

describe("OrderView — the trade", () => {
  const sent = tradeOut({
    state: "offer_sent",
    offer_url: "https://steamcommunity.com/tradeoffer/1000000001/",
    send_until: new Date(Date.now() + 25 * 60_000).toISOString(),
  });

  it.each<[string, Partial<OrderOut>, string | RegExp]>([
    ["paid", { trade: null }, "Покупаем скин — обмен придёт в Steam через минуту."],
    ["buying", { trade: tradeOut() }, "Покупаем скин — обмен придёт в Steam через минуту."],
    ["trade_sent", { trade: sent }, "Обмен отправлен — примите его в Steam."],
    ["delivered", { trade: tradeOut({ state: "accepted" }) }, "Получено"],
    [
      "returned",
      {
        refunded_to: "balance",
        trade: tradeOut({ state: "failed", reason_code: "not_accepted", refunded_to: "balance" }),
      },
      "Обмен не состоялся — деньги вернулись на баланс.",
    ],
    [
      "failed",
      {
        refunded_to: "balance",
        trade: tradeOut({ state: "failed", reason_code: "try_later", refunded_to: "balance" }),
      },
      /Попробуйте через несколько минут/,
    ],
    [
      "buying",
      { trade: tradeOut({ reason_code: "support" }) },
      "Мы проверяем покупку. Статус обновится на этой странице.",
    ],
  ])("a %s order shows the trade card", async (status, over, text) => {
    m.get.mockResolvedValue(
      orderOut(number, { status: status as OrderOut["status"], payable: false, ...over }),
    );
    view();
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(state()).toBe(status);
    expect(screen.getByRole("region", { name: "Обмен в Steam" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Оплатить/ })).toBeNull();
  });

  it("re-reads a moving order and stops once it can no longer change", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    m.get
      .mockResolvedValueOnce(orderOut(number, { status: "buying", payable: false }))
      .mockResolvedValueOnce(
        orderOut(number, { status: "trade_sent", payable: false, trade: sent }),
      )
      .mockResolvedValue(
        orderOut(number, {
          status: "delivered",
          payable: false,
          trade: tradeOut({ state: "accepted" }),
        }),
      );
    view();
    await tick();
    expect(state()).toBe("buying");
    await tick(8_000);
    expect(state()).toBe("trade_sent");
    expect(m.get).toHaveBeenCalledTimes(2);
    await tick(8_000);
    expect(state()).toBe("delivered");
    expect(screen.getByText("Получено")).toBeInTheDocument();
    await tick(10 * 60_000);
    expect(m.get).toHaveBeenCalledTimes(3);
  });

  it("a delivered order is read once and never polled", async () => {
    vi.useFakeTimers();
    m.get.mockResolvedValue(
      orderOut(number, {
        status: "delivered",
        payable: false,
        trade: tradeOut({ state: "accepted" }),
      }),
    );
    view();
    await tick(5 * 60_000);
    expect(state()).toBe("delivered");
    expect(m.get).toHaveBeenCalledTimes(1);
  });
});

describe("OrderView — no order to show", () => {
  it("someone else's or an unknown number reads as not found, and is not asked again", async () => {
    vi.useFakeTimers();
    m.get.mockRejectedValue(new SessionApiError(404, "Not Found", null));
    view();
    await tick();
    expect(screen.getByRole("heading", { name: "Заказ не найден." })).toBeInTheDocument();
    expect(state()).toBe("notFound");
    expect(screen.getByRole("link", { name: "Мои заказы" })).toHaveAttribute(
      "href",
      "/account/orders",
    );
    await tick(60_000);
    expect(m.get).toHaveBeenCalledTimes(1);
  });

  it("an outage offers a retry, in our words", async () => {
    vi.useFakeTimers();
    const outage = new SessionApiError(500, "Internal", { detail: "db exploded" });
    m.get
      .mockRejectedValueOnce(outage)
      .mockRejectedValueOnce(outage)
      .mockRejectedValueOnce(outage)
      .mockResolvedValue(orderOut(number));
    view();
    await tick(5_000); // the query's own two retries
    expect(m.get).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    await tick();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(`Заказ #${number}`);
    expect(screen.queryByText(/exploded/)).toBeNull();
  });

  it("signed out: a way to sign in, and the order is not asked for", () => {
    m.auth.value = { status: "anonymous", user: null, signInHref: (l: string) => `/s?l=${l}` };
    view();
    expect(screen.getByText("Войдите через Steam, чтобы открыть заказы.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute(
      "href",
      "/s?l=ru",
    );
    expect(m.get).not.toHaveBeenCalled();
  });

  it("a suspended account says so", () => {
    m.auth.value = { status: "suspended", user: null, signInHref: () => "" };
    view();
    expect(screen.getByText("Аккаунт заблокирован.")).toBeInTheDocument();
    expect(m.get).not.toHaveBeenCalled();
  });
});
