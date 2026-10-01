// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EntriesList } from "./EntriesList";

import type * as BalanceModule from "@/lib/balance";
import type { EntriesPage, Entry } from "@/lib/balance";

const mocks = vi.hoisted(() => ({
  getEntries: vi.fn<(cursor?: string) => Promise<EntriesPage>>(),
}));
vi.mock("@/lib/balance", async (importOriginal) => ({
  ...(await importOriginal<typeof BalanceModule>()),
  getEntries: mocks.getEntries,
}));

function entry(over: Partial<Entry>): Entry {
  return {
    id: "e1",
    kind: "topup",
    amount_uzs: "+50000",
    created_at: "2026-10-01T09:00:00Z",
    reference_number: "T1",
    ...over,
  };
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <EntriesList locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

/** Text with `Intl`'s no-break spaces read as plain ones. */
const plain = (s: string | null | undefined) => (s ?? "").replace(/\s/g, " ");

describe("EntriesList", () => {
  beforeEach(() => {
    mocks.getEntries.mockReset();
  });

  it("shows signed amounts and kind labels", async () => {
    mocks.getEntries.mockResolvedValue({
      items: [
        entry({ id: "a", kind: "topup", amount_uzs: "+50000" }),
        entry({ id: "b", kind: "topup_reversal", amount_uzs: "-10000" }),
        entry({ id: "c", kind: "admin_adjust", amount_uzs: "+2000", reference_number: null }),
      ],
      next_cursor: null,
    });
    setup();
    expect(await screen.findByText("Пополнение")).toBeInTheDocument();
    expect(screen.getByText("Пополнение отменено")).toBeInTheDocument();
    expect(screen.getByText("Корректировка")).toBeInTheDocument();
    const amounts = screen.getAllByTestId("entry-amount").map((el) => plain(el.textContent));
    expect(amounts).toEqual(["+50 000 сум", "−10 000 сум", "+2 000 сум"]);
    expect(screen.queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
    expect(mocks.getEntries).toHaveBeenCalledWith(undefined);
  });

  it("labels order purchases and refunds", async () => {
    mocks.getEntries.mockResolvedValue({
      items: [
        entry({ id: "p", kind: "purchase", amount_uzs: "-171800", reference_number: null }),
        entry({ id: "r", kind: "refund", amount_uzs: "+171800", reference_number: null }),
      ],
      next_cursor: null,
    });
    setup();
    expect(await screen.findByText("Покупка")).toBeInTheDocument();
    expect(screen.getByText("Возврат на баланс")).toBeInTheDocument();
  });

  it("«Показать ещё» fetches the next page with the cursor", async () => {
    mocks.getEntries
      .mockResolvedValueOnce({ items: [entry({ id: "a" })], next_cursor: "CUR1" })
      .mockResolvedValueOnce({
        items: [entry({ id: "b", kind: "admin_adjust", amount_uzs: "-3000" })],
        next_cursor: null,
      });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByText("Корректировка")).toBeInTheDocument();
    expect(mocks.getEntries).toHaveBeenLastCalledWith("CUR1");
    expect(screen.getByText("Пополнение")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
    });
  });

  it("says so when there is no history yet", async () => {
    mocks.getEntries.mockResolvedValue({ items: [], next_cursor: null });
    setup();
    expect(await screen.findByText("Пока пусто.")).toBeInTheDocument();
  });

  it("offers a retry when the history does not load", async () => {
    mocks.getEntries
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ items: [], next_cursor: null });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Обновить" }));
    expect(await screen.findByText("Пока пусто.")).toBeInTheDocument();
  });
});
