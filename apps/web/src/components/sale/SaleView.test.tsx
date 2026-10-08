// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SaleView } from "./SaleView";

import type * as SalesModule from "@/lib/sales";
import type { SaleOut } from "@/lib/sales";

import { saleOut } from "@/test/sales";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({ getSale: vi.fn() }));
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

const SALE: SaleOut = {
  number: "S7K2M9QX",
  status: "offered",
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
      exterior: "FT",
      rarity_color: "#eb4b4b",
      price_uzs: "149600",
    },
  ],
  offer: {
    url: "https://steamcommunity.com/tradeoffer/6912345678/",
    bot_name: "Bot #3",
    expires_at: "2026-10-08T12:30:00Z",
  },
  money_at: null,
  payout_status: null,
  payout_reject_reason: null,
  created_at: "2026-10-08T10:00:00Z",
};

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <SaleView locale="ru" number="S7K2M9QX" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("SaleView", () => {
  beforeEach(() => {
    api.getSale.mockReset();
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "/auth" };
  });

  it("asks to accept the trade with the offer's link and the bot", async () => {
    api.getSale.mockResolvedValue(SALE);
    view();
    expect(await screen.findByRole("heading", { name: "Примите обмен" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть обмен в Steam" })).toHaveAttribute(
      "href",
      SALE.offer?.url,
    );
    expect(screen.getByText(/Bot #3/)).toBeInTheDocument();
    expect(screen.getAllByText(/158\s300/).length).toBeGreaterThan(0);
  });

  it("while the money waits, says when it comes and never says hold", async () => {
    api.getSale.mockResolvedValue({
      ...SALE,
      status: "hold",
      offer: null,
      money_at: "2026-10-15T10:00:00Z",
    });
    view();
    expect(await screen.findByText("Скины получены")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/холд|hold/i);
  });

  it("names the card by its last four once paid", async () => {
    api.getSale.mockResolvedValue({
      ...SALE,
      status: "payout",
      payout_to: "card",
      card: { type: "humo", last4: "9015" },
      offer: null,
      payout_status: "paid",
      payout_uzs: "147400",
    });
    view();
    expect(await screen.findByText("Деньги отправлены")).toBeInTheDocument();
    expect(screen.getByText(/отправлены на карту .*•••• 9015/)).toBeInTheDocument();
  });

  it("shows why a card payout was rejected and that the money is on the balance", async () => {
    api.getSale.mockResolvedValue({
      ...SALE,
      status: "payout",
      payout_to: "card",
      card: { type: "humo", last4: "9015" },
      offer: null,
      payout_status: "rejected",
      payout_reject_reason: "Карта заблокирована",
    });
    view();
    expect(
      await screen.findByText(
        /Перевод на карту не прошёл: Карта заблокирована\. 155\s200 .* зачислены на ваш баланс/,
      ),
    ).toBeInTheDocument();
  });

  it("a cancelled card payout says the sale did not go through, not that money is coming", async () => {
    api.getSale.mockResolvedValue({
      ...SALE,
      status: "payout",
      payout_to: "card",
      card: { type: "humo", last4: "9015" },
      offer: null,
      payout_status: "canceled",
    });
    view();
    expect(await screen.findByText("Продажа не состоялась")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Скоро отправим/);
  });

  it("a card payout waiting out the days says when the money comes", async () => {
    api.getSale.mockResolvedValue({
      ...SALE,
      status: "payout",
      payout_to: "card",
      card: { type: "humo", last4: "9015" },
      offer: null,
      payout_status: "waiting_hold",
      money_at: "2026-10-15T10:00:00Z",
    });
    view();
    expect(await screen.findByText("Скины получены")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Скоро отправим/);
  });

  it("an offered sale without an offer yet asks to open Steam, with no blanks", async () => {
    api.getSale.mockResolvedValue({ ...SALE, offer: null });
    view();
    expect(await screen.findByRole("heading", { name: "Примите обмен" })).toBeInTheDocument();
    expect(screen.getByText(/откройте Steam/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/прислал|до\s*\./);
  });

  it("says a sale it does not know is not found", async () => {
    api.getSale.mockRejectedValue(new SessionApiError(404, "Not Found", null));
    view();
    expect(await screen.findByText("Продажа не найдена.")).toBeInTheDocument();
  });

  it("while held: the money's day as the badge, the 7 days as the current step, wear on items", async () => {
    api.getSale.mockResolvedValue(saleOut("S7K2M9QX"));
    view();
    expect(await screen.findByTestId("status-badge")).toHaveTextContent("Деньги придут 15 окт.");
    const steps = screen
      .getAllByRole("listitem")
      .map((li) => li.getAttribute("data-state"))
      .filter((x) => x !== null);
    expect(steps).toEqual(["done", "now", "todo"]);
    expect(screen.getByText("Немного поношенное")).toBeInTheDocument();
  });
});
