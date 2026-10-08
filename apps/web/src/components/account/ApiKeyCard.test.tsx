// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiKeyCard } from "./ApiKeyCard";

import type * as ApiKeyModule from "@/lib/api-key";

const api = vi.hoisted(() => ({
  getApiKey: vi.fn(),
  issueApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}));
vi.mock("@/lib/api-key", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiKeyModule>()),
  ...api,
}));

const LIVE = {
  id: "k1",
  pricing_profile: "retail",
  created_at: "2026-10-08T10:00:00Z",
  last_used_at: null,
};
const ISSUED = { ...LIVE, token: "csk_secret-token-123" };

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }} timeZone="UTC">
        <ApiKeyCard locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("ApiKeyCard", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it("issues a key, shows the token once and drops it after «Готово»", async () => {
    api.getApiKey.mockResolvedValueOnce(null).mockResolvedValue(LIVE);
    api.issueApiKey.mockResolvedValue(ISSUED);
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Выпустить ключ" }));
    expect(await screen.findByText("csk_secret-token-123")).toBeInTheDocument();
    expect(screen.getByText(/Сохраните ключ — он больше не покажется/)).toBeInTheDocument();
    expect(api.issueApiKey).toHaveBeenCalledWith(expect.stringMatching(/^web-apikey-/));
    fireEvent.click(screen.getByRole("button", { name: "Скопировать" }));
    await waitFor(() => {
      // eslint-disable-next-line @typescript-eslint/unbound-method -- a vi.fn on the stub
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(ISSUED.token);
    });
    fireEvent.click(screen.getByRole("button", { name: "Готово" }));
    await waitFor(() => {
      expect(screen.queryByText("csk_secret-token-123")).toBeNull();
    });
    expect(await screen.findByRole("button", { name: "Перевыпустить" })).toBeInTheDocument();
  });

  it("shows the live key and asks before reissuing", async () => {
    api.getApiKey.mockResolvedValue(LIVE);
    api.issueApiKey.mockResolvedValue(ISSUED);
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Перевыпустить" }));
    expect(api.issueApiKey).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Да, перевыпустить" }));
    expect(await screen.findByText("csk_secret-token-123")).toBeInTheDocument();
    expect(api.issueApiKey).toHaveBeenCalledTimes(1);
  });

  it("can back out of the confirm", async () => {
    api.getApiKey.mockResolvedValue(LIVE);
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Отозвать" }));
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("button", { name: "Да, отозвать" })).toBeNull();
    expect(api.revokeApiKey).not.toHaveBeenCalled();
  });

  it("revokes after the confirm", async () => {
    api.getApiKey.mockResolvedValueOnce(LIVE).mockResolvedValue(null);
    api.revokeApiKey.mockResolvedValue(undefined);
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Отозвать" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, отозвать" }));
    await waitFor(() => {
      expect(api.revokeApiKey).toHaveBeenCalledWith(expect.stringMatching(/^web-apikey-/));
    });
    expect(await screen.findByRole("button", { name: "Выпустить ключ" })).toBeInTheDocument();
  });

  it("asks for a top-up first when a key is not allowed", async () => {
    const { ApiKeyNotAllowedError } = await vi.importActual<typeof ApiKeyModule>("@/lib/api-key");
    api.getApiKey.mockResolvedValue(null);
    api.issueApiKey.mockRejectedValue(new ApiKeyNotAllowedError());
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Выпустить ключ" }));
    expect(await screen.findByText("Сначала пополните баланс")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выпустить ключ" })).toBeDisabled();
  });

  it("says so when issuing fails", async () => {
    api.getApiKey.mockResolvedValue(null);
    api.issueApiKey.mockRejectedValue(new Error("boom"));
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Выпустить ключ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не получилось");
  });

  it("hides the docs link until the documentation is published", async () => {
    api.getApiKey.mockResolvedValue(LIVE);
    view();
    await screen.findByRole("button", { name: "Отозвать" });
    expect(screen.queryByRole("link", { name: "Документация API" })).toBeNull();
  });
});
