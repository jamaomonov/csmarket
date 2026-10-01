// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BalanceView } from "./BalanceView";

import type * as BalanceModule from "@/lib/balance";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
const api = vi.hoisted(() => ({
  getBalance: vi.fn(),
  getProviders: vi.fn(),
  getEntries: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("@/lib/balance", async (importOriginal) => ({
  ...(await importOriginal<typeof BalanceModule>()),
  ...api,
}));
vi.mock("@/i18n/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <BalanceView locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("BalanceView", () => {
  beforeEach(() => {
    api.getBalance.mockReset().mockResolvedValue({ balance_uzs: "150000" });
    api.getProviders.mockReset().mockResolvedValue([{ slug: "click" }]);
    api.getEntries.mockReset().mockResolvedValue({ items: [], next_cursor: null });
  });

  it("offers Steam sign-in when signed out and fetches nothing", () => {
    auth.value = { status: "anonymous", user: null, signInHref: (l: string) => `/start?l=${l}` };
    renderView();
    expect(screen.getByText("Войдите через Steam, чтобы открыть баланс.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute(
      "href",
      "/start?l=ru",
    );
    expect(api.getBalance).not.toHaveBeenCalled();
  });

  it("says so when the account is suspended", () => {
    auth.value = { status: "suspended", user: null, signInHref: () => "" };
    renderView();
    expect(screen.getByText("Аккаунт заблокирован.")).toBeInTheDocument();
  });

  it("shows the balance, the top-up form and the history when signed in", async () => {
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "" };
    renderView();
    const amount = await screen.findByText(/^150\s000 сум$/);
    expect(amount).toBeInTheDocument();
    expect(screen.getByText("На балансе")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Click" })).toBeInTheDocument();
    expect(await screen.findByText("Пока пусто.")).toBeInTheDocument();
  });
});
