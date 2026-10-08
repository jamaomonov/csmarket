// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OrderOut } from "@/lib/orders";
import type { ReactNode } from "react";

import { orderKey } from "@/lib/orders";
import { orderState as state, renderOrderView, tick } from "@/test/order-view";
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
describe("OrderView — the trade", () => {
  const sent = tradeOut({
    state: "offer_sent",
    offer_url: "https://steamcommunity.com/tradeoffer/1000000001/",
    send_until: new Date(Date.now() + 25 * 60_000).toISOString(),
  });

  it.each<[OrderOut["status"], Partial<OrderOut>, string | RegExp]>([
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
    m.get.mockResolvedValue(orderOut(number, { status, payable: false, ...over }));
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

  it("a socket nudge re-reads the order at once, and polling keeps running", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    m.get
      .mockResolvedValueOnce(orderOut(number, { status: "buying", payable: false }))
      .mockResolvedValue(orderOut(number, { status: "trade_sent", payable: false, trade: sent }));
    const { client } = view();
    await tick();
    expect(state()).toBe("buying");
    await act(async () => {
      await client.invalidateQueries({ queryKey: orderKey(number) });
    });
    await tick();
    expect(state()).toBe("trade_sent");
    expect(m.get).toHaveBeenCalledTimes(2);
    await tick(8_000);
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

  it("a trade accepted in Steam's hold reads «Получен», every step done", async () => {
    m.get.mockResolvedValue(
      orderOut(number, {
        status: "trade_sent",
        payable: false,
        paid_at: "2026-10-08T15:50:00Z",
        trade: tradeOut({ state: "accepted", release_date: "2026-10-15T15:52:00Z" }),
      }),
    );
    view();
    const label = await screen.findByTestId("order-status-label");
    expect(label).toHaveTextContent("Получен");
    const steps = screen.getAllByRole("listitem").map((li) => li.getAttribute("data-state"));
    expect(steps).toEqual(["done", "done", "done"]);
    expect(screen.queryByText(/защищает/)).toBeNull();
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
    expect(screen.getByRole("link", { name: "← К обменам" })).toHaveAttribute("href", "/account/trades");
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
