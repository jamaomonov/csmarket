// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SalesList } from "./SalesList";

import type * as SalesModule from "@/lib/sales";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({ listSales: vi.fn() }));
vi.mock("@/lib/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof SalesModule>()),
  ...api,
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <SalesList locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("SalesList", () => {
  beforeEach(() => {
    api.listSales.mockReset();
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "/auth" };
  });

  it("links each sale with its first item, payout and status", async () => {
    api.listSales.mockResolvedValue({
      items: [
        {
          number: "S7K2M9QX",
          status: "hold",
          payout_to: "balance",
          card: null,
          items_uzs: "155200",
          bonus_uzs: "3100",
          fee_uzs: "0",
          payout_uzs: "158300",
          items: [
            {
              asset_id: "100",
              name: "AK-47 | Redline (Field-Tested)",
              image_url: null,
              price_uzs: "149600",
            },
            {
              asset_id: "101",
              name: "P250 | Sand Dune (Field-Tested)",
              image_url: null,
              price_uzs: "5600",
            },
          ],
          offer: null,
          money_at: "2026-10-15T10:00:00Z",
          payout_status: null,
          payout_reject_reason: null,
          created_at: "2026-10-08T10:00:00Z",
        },
      ],
      next_cursor: null,
    });
    view();
    const link = await screen.findByRole("link", { name: /AK-47 \| Redline/ });
    expect(link).toHaveAttribute("href", "/account/sales/S7K2M9QX");
    expect(link).toHaveTextContent("+1");
    expect(link).toHaveTextContent(/158\s300/);
    expect(link).toHaveTextContent("Ждём 7 дней");
  });

  it("says when there are none", async () => {
    api.listSales.mockResolvedValue({ items: [], next_cursor: null });
    view();
    expect(await screen.findByText("Продаж пока нет.")).toBeInTheDocument();
  });

  it("shows nothing, not a skeleton forever, when signed out", () => {
    auth.value = { status: "signed_out", user: null, signInHref: () => "/auth" };
    const { container } = view();
    expect(container.querySelector("[aria-busy]")).toBeNull();
    expect(api.listSales).not.toHaveBeenCalled();
  });

  it("says the list failed to load", async () => {
    api.listSales.mockRejectedValue(new Error("boom"));
    view();
    expect(await screen.findByText(/Не получилось загрузить продажи/)).toBeInTheDocument();
  });
});
