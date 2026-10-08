// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CardsList } from "./CardsList";

import type * as SalesModule from "@/lib/sales";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({ listCards: vi.fn(), deleteCard: vi.fn() }));
vi.mock("@/lib/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof SalesModule>()),
  ...api,
}));

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <CardsList locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("CardsList", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "/auth" };
  });

  it("lists cards by brand and last four, and forgets one with a key", async () => {
    api.listCards.mockResolvedValue({
      items: [{ id: "c1", type: "humo", last4: "9015", created_at: "2026-10-08T10:00:00Z" }],
    });
    api.deleteCard.mockResolvedValue(undefined);
    view();
    expect(await screen.findByText("Humo •••• 9015")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Удалить Humo •••• 9015" }));
    await waitFor(() => {
      expect(api.deleteCard).toHaveBeenCalledWith("c1", expect.stringMatching(/^web-card-/));
    });
  });

  it("says where a card comes from when there is none", async () => {
    api.listCards.mockResolvedValue({ items: [] });
    view();
    expect(await screen.findByText(/Карту можно добавить при продаже/)).toBeInTheDocument();
  });
});
