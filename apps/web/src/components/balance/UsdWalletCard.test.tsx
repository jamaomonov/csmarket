// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UsdWalletCard } from "./UsdWalletCard";

import type * as BalanceModule from "@/lib/balance";
import type { ConvertOut, UsdWallet } from "@/lib/balance";

import { BALANCE_KEY } from "@/lib/balance";

const mocks = vi.hoisted(() => ({
  convertToUsd: vi.fn<(amount: number, key: string) => Promise<ConvertOut>>(),
}));
vi.mock("@/lib/balance", async (importOriginal) => ({
  ...(await importOriginal<typeof BalanceModule>()),
  convertToUsd: mocks.convertToUsd,
}));

const USD: UsdWallet = { balance_usd: "7.826", rate_uzs: "12777.01" };
const OUT: ConvertOut = {
  amount_uzs: "100000",
  amount_usd: "7.826",
  rate_uzs: "12777.01",
  balance_uzs: "0",
  balance_usd: "15.652",
};

function setup(usd: UsdWallet = USD) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <UsdWalletCard locale="ru" usd={usd} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
  return { invalidate };
}

const field = () => screen.getByLabelText("Сумма в сумах");

describe("UsdWalletCard", () => {
  beforeEach(() => {
    mocks.convertToUsd.mockReset();
  });

  it("shows the dollar balance and the preview", () => {
    setup();
    expect(screen.getByText("$7.826")).toBeTruthy();
    fireEvent.change(field(), { target: { value: "100000" } });
    expect(screen.getByText(/≈ \$7\.826 по курсу/).textContent.replace(/\s/g, " ")).toBe(
      "≈ $7.826 по курсу 12 777,01",
    );
  });

  it("converts once with a key and re-reads the balance", async () => {
    mocks.convertToUsd.mockResolvedValue(OUT);
    const { invalidate } = setup();
    fireEvent.change(field(), { target: { value: "100000" } });
    fireEvent.click(screen.getByRole("button", { name: "Перевести" }));
    await waitFor(() => {
      expect(mocks.convertToUsd).toHaveBeenCalledTimes(1);
    });
    const [amount, key] = mocks.convertToUsd.mock.calls[0] ?? [];
    expect(amount).toBe(100000);
    expect(key?.length).toBeGreaterThanOrEqual(16);
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith(expect.objectContaining({ queryKey: BALANCE_KEY }));
    });
    await screen.findByText("Переведено.");
  });

  it("says when the balance is too low", async () => {
    mocks.convertToUsd.mockRejectedValueOnce(
      new SessionApiError(409, "Conflict", { code: "balance_too_low" }),
    );
    setup();
    fireEvent.change(field(), { target: { value: "100000" } });
    fireEvent.click(screen.getByRole("button", { name: "Перевести" }));
    await screen.findByText("Не хватает денег на балансе");
    expect(mocks.convertToUsd).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Переведено.")).toBeNull();
  });

  it("is disabled while the rate is unavailable", () => {
    setup({ balance_usd: "1.000", rate_uzs: null });
    expect(screen.getByText("Курс сейчас недоступен")).toBeTruthy();
    expect(field()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Перевести" })).toBeDisabled();
  });

  const type = (v: string) => {
    fireEvent.change(field(), { target: { value: v } });
  };
  const send = () => {
    fireEvent.click(screen.getByRole("button", { name: "Перевести" }));
  };
  const keyOf = (n: number) => mocks.convertToUsd.mock.calls[n]?.[1];

  it("reuses the key after a code-less failure, drops it after an answer or a new amount", async () => {
    mocks.convertToUsd
      .mockRejectedValueOnce(new Error("network"))
      .mockRejectedValueOnce(new Error("network"))
      .mockRejectedValueOnce(new SessionApiError(409, "Conflict", { code: "balance_too_low" }))
      .mockResolvedValue(OUT);
    setup();
    type("100000");
    send();
    await screen.findByText("Не получилось перевести. Попробуйте ещё раз.");
    send();
    await waitFor(() => {
      expect(mocks.convertToUsd).toHaveBeenCalledTimes(2);
    });
    expect(keyOf(1)).toBe(keyOf(0));
    await screen.findByText("Не получилось перевести. Попробуйте ещё раз.");
    // New amount after a code-less failure: a fresh key.
    type("200000");
    send();
    await waitFor(() => {
      expect(mocks.convertToUsd).toHaveBeenCalledTimes(3);
    });
    expect(keyOf(2)).not.toBe(keyOf(1));
    await screen.findByText("Не хватает денег на балансе");
    // After balance_too_low: fresh key.
    send();
    await waitFor(() => {
      expect(mocks.convertToUsd).toHaveBeenCalledTimes(4);
    });
    expect(keyOf(3)).not.toBe(keyOf(2));
    await screen.findByText("Переведено.");
    expect(field()).toHaveValue("");
    // After success: fresh key.
    type("200000");
    send();
    await waitFor(() => {
      expect(mocks.convertToUsd).toHaveBeenCalledTimes(5);
    });
    expect(keyOf(4)).not.toBe(keyOf(3));
  });

  it("still says done when the re-read fails", async () => {
    mocks.convertToUsd.mockResolvedValue(OUT);
    const { invalidate } = setup();
    invalidate.mockRejectedValue(new Error("down"));
    type("100000");
    send();
    await screen.findByText("Переведено.");
    expect(screen.queryByText("Не получилось перевести. Попробуйте ещё раз.")).toBeNull();
  });

  it("shows the rate copy on rate_unavailable", async () => {
    mocks.convertToUsd.mockRejectedValueOnce(
      new SessionApiError(503, "Unavailable", { code: "rate_unavailable" }),
    );
    setup();
    type("100000");
    send();
    await screen.findByText("Курс сейчас недоступен");
  });
});
