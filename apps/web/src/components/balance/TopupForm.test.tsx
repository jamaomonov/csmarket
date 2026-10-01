// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TopupForm } from "./TopupForm";

import type * as BalanceModule from "@/lib/balance";
import type { Provider, Topup, TopupRequest } from "@/lib/balance";

import { groupDigits } from "@/lib/amount-input";

const mocks = vi.hoisted(() => ({
  createTopup: vi.fn<(body: TopupRequest, key: string) => Promise<Topup>>(),
  push: vi.fn(),
}));
vi.mock("@/lib/balance", async (importOriginal) => ({
  ...(await importOriginal<typeof BalanceModule>()),
  createTopup: mocks.createTopup,
}));
vi.mock("@/i18n/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));

const TOPUP: Topup = {
  number: "T123",
  amount_uzs: "100000",
  provider: "click",
  status: "pending",
  expires_at: "2026-10-01T12:30:00Z",
  intent_url: "https://kassa.example/pay",
};

function setup(providers: Provider[] | undefined = [{ slug: "click" }, { slug: "mock" }]) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <TopupForm locale="ru" providers={providers} />
    </NextIntlClientProvider>,
  );
}

const field = () => screen.getByLabelText("Сумма");
const submit = () => screen.getByRole("button", { name: /^Пополнить на|^Введите сумму/ });

describe("TopupForm", () => {
  beforeEach(() => {
    mocks.createTopup.mockReset();
    mocks.push.mockReset();
  });

  it("a quick amount fills the field and the button", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: groupDigits("50000", "ru") }));
    expect(field()).toHaveValue(groupDigits("50000", "ru"));
    expect(submit().textContent.replace(/\s/g, " ")).toBe("Пополнить на 50 000 сум");
  });

  it("asks for an amount before there is one", () => {
    setup();
    expect(submit()).toHaveTextContent("Введите сумму");
    expect(submit()).toBeDisabled();
  });

  it("groups typed digits and states the bounds up front", () => {
    setup();
    fireEvent.change(field(), { target: { value: "250000" } });
    expect(field()).toHaveValue(groupDigits("250000", "ru"));
    expect(screen.getByText(/^От 1\s000 сум до 10\s000\s000 сум$/)).toBeInTheDocument();
  });

  it("refuses 999 on the spot and never calls the API", () => {
    setup();
    fireEvent.change(field(), { target: { value: "999" } });
    fireEvent.click(submit());
    expect(screen.getByRole("alert")).toHaveTextContent(/без тийинов/);
    expect(mocks.createTopup).not.toHaveBeenCalled();
  });

  it("refuses more than the ceiling too", () => {
    setup();
    fireEvent.change(field(), { target: { value: "10000001" } });
    fireEvent.click(submit());
    expect(screen.getByRole("alert")).toHaveTextContent(/без тийинов/);
    expect(mocks.createTopup).not.toHaveBeenCalled();
  });

  it("opens the top-up with an idempotency key and goes to its page", async () => {
    mocks.createTopup.mockResolvedValue(TOPUP);
    setup();
    fireEvent.click(screen.getByRole("button", { name: groupDigits("100000", "ru") }));
    expect(screen.getByRole("button", { name: "Click" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(submit());
    await waitFor(() => {
      expect(mocks.push).toHaveBeenCalledWith("/account/balance/topups/T123?go=1");
    });
    const [body, key] = mocks.createTopup.mock.calls[0] ?? [];
    expect(body).toEqual({ amount_uzs: 100_000, provider: "click", locale: "ru" });
    expect(key?.length).toBeGreaterThanOrEqual(16);
  });

  it("a retry after a failure replays the same key; another provider gets a new one", async () => {
    mocks.createTopup
      .mockRejectedValueOnce(new SessionApiError(503, "Unavailable", null))
      .mockRejectedValueOnce(new SessionApiError(503, "Unavailable", null))
      .mockResolvedValue(TOPUP);
    setup();
    fireEvent.click(screen.getByRole("button", { name: groupDigits("50000", "ru") }));
    fireEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не получилось начать оплату. Попробуйте ещё раз.",
    );
    fireEvent.click(submit());
    await waitFor(() => {
      expect(mocks.createTopup).toHaveBeenCalledTimes(2);
    });
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Тестовая оплата" }));
    fireEvent.click(submit());
    await waitFor(() => {
      expect(mocks.push).toHaveBeenCalled();
    });
    const keys = mocks.createTopup.mock.calls.map(([, key]) => key);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
    expect(mocks.createTopup.mock.calls[2]?.[0].provider).toBe("mock");
  });

  it("explains an amount the API refused", async () => {
    mocks.createTopup.mockRejectedValue(
      new SessionApiError(422, "Unprocessable", { code: "topup_amount" }),
    );
    setup();
    fireEvent.click(screen.getByRole("button", { name: groupDigits("50000", "ru") }));
    fireEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent(/без тийинов/);
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("a second submit while the first request is in flight opens nothing more", async () => {
    let finish: (t: Topup) => void = () => undefined;
    mocks.createTopup.mockReturnValue(
      new Promise<Topup>((resolve) => {
        finish = resolve;
      }),
    );
    setup();
    fireEvent.click(screen.getByRole("button", { name: groupDigits("50000", "ru") }));
    const form = field().closest("form");
    if (!form) throw new Error("no form");
    fireEvent.submit(form);
    fireEvent.submit(form);
    fireEvent.click(submit());
    expect(submit()).toBeDisabled();
    finish(TOPUP);
    await waitFor(() => {
      expect(mocks.push).toHaveBeenCalledTimes(1);
    });
    expect(mocks.createTopup).toHaveBeenCalledTimes(1);
  });

  it("is usable again if the page stays after going to the top-up", async () => {
    mocks.createTopup.mockResolvedValue(TOPUP);
    setup();
    fireEvent.click(screen.getByRole("button", { name: groupDigits("50000", "ru") }));
    fireEvent.click(submit());
    await waitFor(() => {
      expect(mocks.push).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(submit()).toBeEnabled();
    });
  });

  it("a rate-limited request reads as a failure to start", async () => {
    mocks.createTopup.mockRejectedValue(
      new SessionApiError(429, "Too Many Requests", { code: "rate_limited" }),
    );
    setup();
    fireEvent.click(screen.getByRole("button", { name: groupDigits("50000", "ru") }));
    fireEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не получилось начать оплату. Попробуйте ещё раз.",
    );
    expect(submit()).toBeEnabled();
  });

  it("a paste never shows more digits than the field holds", () => {
    setup();
    fireEvent.paste(field(), { clipboardData: { getData: () => "12345678901234567890" } });
    expect(field()).toHaveValue(groupDigits("123456789012", "ru"));
  });

  it("shows kassa names as brands and the dev kassa as a test payment", () => {
    setup([{ slug: "click" }, { slug: "payme" }, { slug: "uzum" }, { slug: "mock" }]);
    for (const name of ["Click", "Payme", "Uzum", "Тестовая оплата"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("says top-ups are unavailable when no kassa is open", () => {
    setup([]);
    expect(screen.getByText("Пополнение сейчас недоступно.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: groupDigits("50000", "ru") }));
    expect(submit()).toBeDisabled();
  });
});
