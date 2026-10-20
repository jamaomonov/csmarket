// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DepositView } from "./DepositView";

import type * as BalanceModule from "@/lib/balance";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
const api = vi.hoisted(() => ({ getProviders: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("@/lib/balance", async (importOriginal) => ({
  ...(await importOriginal<typeof BalanceModule>()),
  ...api,
}));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <DepositView locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("DepositView", () => {
  beforeEach(() => {
    api.getProviders.mockReset().mockResolvedValue([
      { slug: "click", fee_pct: "0" },
      { slug: "payme", fee_pct: "0" },
    ]);
  });

  it("the wallet: the kassas and the amount, no deposit / withdraw switch", async () => {
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "" };
    renderView();
    expect(screen.getByRole("heading", { level: 1, name: "Кошелёк" })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(await screen.findByRole("button", { name: "Payme" })).toBeInTheDocument();
    expect(screen.getByLabelText("Сумма")).toBeInTheDocument();
  });

  it("a visitor is asked to sign in", () => {
    auth.value = { status: "anonymous", user: null, signInHref: (l: string) => `/in?l=${l}` };
    renderView();
    expect(screen.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute(
      "href",
      "/in?l=ru",
    );
    expect(api.getProviders).not.toHaveBeenCalled();
  });
});
