// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PartnerView } from "./PartnerView";

import type { PartnerMe, PartnerRewards } from "@/lib/referrals";

const api = vi.hoisted(() => ({ getPartner: vi.fn(), getRewards: vi.fn() }));
vi.mock("@/lib/referrals", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));
interface AuthMock {
  status: string;
  user: { roles: string[] } | null;
  signInHref: () => string;
}
const auth = vi.hoisted((): { value: AuthMock } => ({
  value: { status: "signed_in", user: { roles: ["partner"] }, signInHref: () => "/in" },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));

const ME: PartnerMe = {
  code: "zufarmax",
  percent: "1.0",
  term_months: 6,
  active: true,
  month: { visits: 12, accounts: 3, purchases: 2, earned_uzs: "3436" },
  all_time: { visits: 40, accounts: 9, purchases: 7, earned_uzs: "12000" },
  held_uzs: "3436",
  next_available_at: "2026-11-03T10:00:00Z",
  credited_uzs: "8564",
};
const REWARD = {
  delivered_at: "2026-10-26T10:00:00Z",
  base_uzs: "171800",
  amount_uzs: "1718",
  status: "held",
  available_at: "2026-11-03T10:00:00Z",
} as const;

function renderView() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <PartnerView locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("PartnerView", () => {
  beforeEach(() => {
    api.getPartner.mockReset().mockResolvedValue(ME);
    api.getRewards.mockReset().mockResolvedValue({ items: [REWARD], next_cursor: null });
    auth.value = { status: "signed_in", user: { roles: ["partner"] }, signInHref: () => "/in" };
  });

  it("shows the link, the terms and the money", async () => {
    renderView();
    expect(await screen.findByDisplayValue("https://csmarket.uz/?ref=zufarmax")).toBeVisible();
    expect(screen.getByText("1 % с покупок · 6 месяцев")).toBeInTheDocument();
    expect(screen.getByText("В ожидании")).toBeInTheDocument();
    expect(screen.getByText("Начислено")).toBeInTheDocument();
    expect(await screen.findByText("В ожидании до 3 нояб. 2026 г.")).toBeInTheDocument();
  });

  it("says «навсегда» and marks a switched-off partner", async () => {
    api.getPartner.mockResolvedValue({ ...ME, term_months: null, active: false });
    renderView();
    expect(await screen.findByText("1 % с покупок · навсегда")).toBeInTheDocument();
    expect(screen.getByText("Отключена")).toBeInTheDocument();
  });

  it("explains the invitation to a non-partner", async () => {
    api.getPartner.mockResolvedValue(null);
    renderView();
    expect(await screen.findByText(/по приглашению/)).toBeInTheDocument();
  });

  it("asks a signed-out visitor to sign in", () => {
    auth.value = { status: "anonymous", user: null, signInHref: () => "/in" };
    renderView();
    expect(screen.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute("href", "/in");
  });

  it("«Показать ещё» fetches the next page", async () => {
    api.getRewards
      .mockResolvedValueOnce({ items: [REWARD], next_cursor: "c1" } satisfies PartnerRewards)
      .mockResolvedValueOnce({
        items: [{ ...REWARD, status: "credited" }],
        next_cursor: null,
      } satisfies PartnerRewards);
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    await waitFor(() => {
      expect(api.getRewards).toHaveBeenLastCalledWith("c1");
    });
    expect(await screen.findByText("Начислено", { selector: "span" })).toBeInTheDocument();
  });
});
