// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TopupStatus } from "./TopupStatus";

import type * as BalanceModule from "@/lib/balance";
import type { Topup } from "@/lib/balance";
import type { ReactNode } from "react";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
const api = vi.hoisted(() => ({
  getTopup: vi.fn<(number: string, locale?: string) => Promise<Topup>>(),
  devPay: vi.fn<(number: string) => Promise<Topup>>(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("@/lib/balance", async (importOriginal) => ({
  ...(await importOriginal<typeof BalanceModule>()),
  ...api,
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const KASSA = "https://kassa.example/pay?id=1";
let seq = 0;
let number = "T1";

function topup(overrides: Partial<Topup> = {}): Topup {
  return {
    number,
    amount_uzs: "100000",
    provider: "click",
    status: "pending",
    expires_at: "2026-10-01T12:30:00Z",
    intent_url: KASSA,
    ...overrides,
  };
}

const assign = vi.fn<(url: string) => void>();

function at(search: string): void {
  vi.stubGlobal("location", {
    pathname: `/account/balance/topups/${number}`,
    search,
    hash: "",
    assign,
  });
}

function view() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <TopupStatus locale="ru" number={number} />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  return { ...render(tree), client };
}

/**
 * Run `ms` of timers under fake timers, plus a little: a query's answer reaches React
 * through a chain of 0 ms timers of its own.
 */
async function tick(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms + 20);
  });
}

describe("TopupStatus", () => {
  beforeEach(() => {
    seq += 1;
    number = `T${seq.toString()}`; // the once-per-tab mark is per number
    auth.value = {
      status: "signed_in",
      user: { id: "u1" },
      signInHref: (l: string) => `/s?l=${l}`,
    };
    api.getTopup.mockReset();
    api.devPay.mockReset();
    assign.mockReset();
    at("");
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("waits for a payment: amount, a way to the kassa, no automatic opening without ?go=1", async () => {
    api.getTopup.mockResolvedValue(topup());
    view();
    expect(await screen.findByRole("heading", { name: "Ждём оплату" })).toBeInTheDocument();
    expect(screen.getByText(/^100\s000 сум$/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Перейти к оплате" })).toHaveAttribute("href", KASSA);
    expect(api.getTopup).toHaveBeenCalledWith(number, "ru");
    expect(assign).not.toHaveBeenCalled();
  });

  it("with ?go=1 opens the kassa once, strips the flag and never again in this tab", async () => {
    const replace = vi.spyOn(window.history, "replaceState");
    at("?go=1");
    api.getTopup.mockResolvedValue(topup());
    const first = view();
    await screen.findByRole("heading", { name: "Ждём оплату" });
    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith(KASSA);
    expect(replace).toHaveBeenCalledWith(null, "", `/account/balance/topups/${number}`);
    await act(() => first.client.refetchQueries());
    first.unmount();
    // A reload that still carries the flag (the strip never landed).
    view();
    await screen.findByRole("heading", { name: "Ждём оплату" });
    expect(assign).toHaveBeenCalledTimes(1);
  });

  it("does not open a kassa when the answer comes too late to be part of the tap", async () => {
    vi.useFakeTimers();
    at("?go=1");
    api.getTopup.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => {
            resolve(topup());
          }, 9_000);
        }),
    );
    view();
    await tick(9_000);
    expect(screen.getByRole("link", { name: "Перейти к оплате" })).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it("the dev kassa pays from the page and never opens anything", async () => {
    at("?go=1");
    api.getTopup
      .mockResolvedValueOnce(topup({ provider: "mock", intent_url: "/topups/x?mock=1" }))
      .mockResolvedValue(topup({ provider: "mock", status: "succeeded", intent_url: null }));
    api.devPay.mockResolvedValue(
      topup({ provider: "mock", status: "succeeded", intent_url: null }),
    );
    view();
    const pay = await screen.findByRole("button", { name: "Оплатить (тест)" });
    expect(screen.queryByRole("link", { name: "Перейти к оплате" })).toBeNull();
    expect(assign).not.toHaveBeenCalled();
    fireEvent.click(pay);
    expect(
      await screen.findByRole("heading", { name: /^Баланс пополнен на 100\s000 сум$/ }),
    ).toBeInTheDocument();
    expect(api.devPay).toHaveBeenCalledWith(number);
  });

  it("says so when the dev payment fails", async () => {
    api.getTopup.mockResolvedValue(topup({ provider: "mock", intent_url: "/x?mock=1" }));
    api.devPay.mockRejectedValue(new SessionApiError(500, "Internal", null));
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Оплатить (тест)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Что-то пошло не так. Попробуйте ещё раз.",
    );
  });

  it("confirms a top-up and refreshes the balance", async () => {
    api.getTopup.mockResolvedValue(topup({ status: "succeeded", intent_url: null }));
    const { client } = view();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    expect(
      await screen.findByRole("heading", { name: /^Баланс пополнен на 100\s000 сум$/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "К балансу" })).toHaveAttribute(
      "href",
      "/account/balance",
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet", "balance"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet", "entries"] });
  });

  it.each([
    ["expired", topup({ status: "expired", intent_url: null })],
    ["past its time, not yet swept", topup({ status: "pending", intent_url: null })],
  ])("an %s top-up asks for a new one and offers nothing to pay", async (_, answer) => {
    at("?go=1");
    api.getTopup.mockResolvedValue(answer);
    view();
    expect(
      await screen.findByRole("heading", {
        name: "Время на оплату вышло. Создайте новое пополнение.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "К балансу" })).toHaveAttribute(
      "href",
      "/account/balance",
    );
    expect(screen.queryByRole("link", { name: "Перейти к оплате" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Оплатить (тест)" })).toBeNull();
    expect(assign).not.toHaveBeenCalled();
  });

  it("a reversed top-up says it was cancelled", async () => {
    api.getTopup.mockResolvedValue(topup({ status: "reversed", intent_url: null }));
    view();
    expect(
      await screen.findByRole("heading", { name: "Пополнение отменено." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "К балансу" })).toBeInTheDocument();
  });

  it("someone else's or an unknown number reads as not found, and is not asked again", async () => {
    vi.useFakeTimers();
    api.getTopup.mockRejectedValue(new SessionApiError(404, "Not Found", null));
    view();
    await tick();
    expect(screen.getByRole("heading", { name: "Пополнение не найдено." })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "К балансу" })).toBeInTheDocument();
    await tick(30_000);
    expect(api.getTopup).toHaveBeenCalledTimes(1);
  });

  it("offers Steam sign-in when signed out and fetches nothing", () => {
    auth.value = { status: "anonymous", user: null, signInHref: (l: string) => `/s?l=${l}` };
    view();
    expect(screen.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute(
      "href",
      "/s?l=ru",
    );
    expect(api.getTopup).not.toHaveBeenCalled();
  });

  it("polls every 3 s and stops once the top-up is paid", async () => {
    vi.useFakeTimers();
    api.getTopup
      .mockResolvedValueOnce(topup())
      .mockResolvedValueOnce(topup())
      .mockResolvedValue(topup({ status: "succeeded", intent_url: null }));
    view();
    await tick();
    expect(api.getTopup).toHaveBeenCalledTimes(1);
    await tick(3_000);
    expect(api.getTopup).toHaveBeenCalledTimes(2);
    await tick(3_000);
    expect(api.getTopup).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("heading", { name: /^Баланс пополнен на/ })).toBeInTheDocument();
    await tick(30_000);
    expect(api.getTopup).toHaveBeenCalledTimes(3);
  });

  it("gives up after two minutes with a refresh that starts over", async () => {
    vi.useFakeTimers();
    api.getTopup.mockResolvedValue(topup());
    view();
    await tick();
    for (let i = 0; i < 45; i += 1) await tick(3_000);
    expect(api.getTopup).toHaveBeenCalledTimes(41);
    const refresh = screen.getByRole("button", { name: "Обновить" });
    fireEvent.click(refresh);
    await tick();
    expect(api.getTopup).toHaveBeenCalledTimes(42);
    expect(screen.queryByRole("button", { name: "Обновить" })).toBeNull();
    await tick(3_000);
    expect(api.getTopup).toHaveBeenCalledTimes(43);
  });
});
