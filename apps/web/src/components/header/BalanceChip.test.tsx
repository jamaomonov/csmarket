// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BalanceChip } from "./BalanceChip";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
const api = vi.hoisted(() => ({ getBalance: vi.fn(), getPendingSales: vi.fn() }));
vi.mock("@/lib/balance", () => ({ BALANCE_KEY: ["balance"], getBalance: api.getBalance }));
vi.mock("@/lib/sales", () => ({
  PENDING_KEY: ["sales", "pending"],
  getPendingSales: api.getPendingSales,
}));

function view(compact = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <BalanceChip compact={compact} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("BalanceChip", () => {
  beforeEach(() => {
    api.getBalance.mockResolvedValue({ balance_uzs: "86700" });
  });

  it("links the money on hold to the sales that wait", async () => {
    api.getPendingSales.mockResolvedValue({ pending_uzs: "10900" });
    view();
    const hold = await screen.findByTestId("balance-hold");
    expect(hold).toHaveAttribute("href", "/account/trades?type=hold");
    expect(hold).toHaveTextContent(/\+10\s900 сум в холде/);
  });

  it("says nothing about a hold when nothing waits", async () => {
    api.getPendingSales.mockResolvedValue({ pending_uzs: "0" });
    view();
    expect(await screen.findByText(/86\s700/)).toBeInTheDocument();
    expect(screen.queryByTestId("balance-hold")).toBeNull();
  });

  it("on phones, fits one line: an hourglass and the sum, the words kept for screen readers", async () => {
    api.getPendingSales.mockResolvedValue({ pending_uzs: "136350" });
    view(true);
    const hold = await screen.findByTestId("balance-hold");
    expect(hold).toHaveTextContent(/^\+136\s350$/);
    expect(hold).toHaveAccessibleName(/\+136\s350 сум в холде/);
  });
});
