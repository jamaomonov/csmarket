// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiKeyCard } from "./ApiKeyCard";

import type * as ApiKeyModule from "@/lib/api-key";

import { IpAllowlistInvalidError } from "@/lib/api-key";

const api = vi.hoisted(() => ({
  getApiKey: vi.fn(),
  issueApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
  setIpAllowlist: vi.fn(),
}));
vi.mock("@/lib/api-key", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiKeyModule>()),
  ...api,
}));

const cache = { qc: null as QueryClient | null };
const LIVE = {
  id: "k1",
  pricing_profile: "retail",
  created_at: "2026-10-08T10:00:00Z",
  last_used_at: null,
  ip_allowlist: [] as string[],
};
const ISSUED = { ...LIVE, token: "csk_secret-token-123" };

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  cache.qc = qc;
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }} timeZone="UTC">
        <ApiKeyCard locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("ApiKeyCard", () => {
  const realClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  const realExec: unknown = Reflect.get(document, "execCommand");
  afterEach(() => {
    if (realClipboard) Object.defineProperty(navigator, "clipboard", realClipboard);
    else Reflect.deleteProperty(navigator, "clipboard");
    Reflect.set(document, "execCommand", realExec);
  });

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
    const again = screen.getByRole("button", { name: "Выпустить ключ" });
    expect(again).toBeEnabled();
    api.issueApiKey.mockResolvedValue(ISSUED);
    fireEvent.click(again);
    expect(await screen.findByText(ISSUED.token)).toBeInTheDocument();
    expect(screen.queryByText("Сначала пополните баланс")).toBeNull();
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

  it("does not keep the token in the mutation cache after «Готово»", async () => {
    api.getApiKey.mockResolvedValueOnce(null).mockResolvedValue(LIVE);
    api.issueApiKey.mockResolvedValue(ISSUED);
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Выпустить ключ" }));
    await screen.findByText(ISSUED.token);
    fireEvent.click(screen.getByRole("button", { name: "Готово" }));
    await waitFor(() => {
      expect(screen.queryByText(ISSUED.token)).toBeNull();
    });
    const held = cache.qc?.getMutationCache().getAll() ?? [];
    expect(JSON.stringify(held.map((m) => m.state.data ?? null))).not.toContain(ISSUED.token);
    expect(document.body.textContent).not.toContain(ISSUED.token);
  });

  it("asks to copy by hand when there is no clipboard and copying fails", async () => {
    Object.assign(navigator, { clipboard: undefined });
    const exec = vi.fn().mockReturnValue(false);
    Object.assign(document, { execCommand: exec });
    api.getApiKey.mockResolvedValue(null);
    api.issueApiKey.mockResolvedValue(ISSUED);
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Выпустить ключ" }));
    await screen.findByText(ISSUED.token);
    fireEvent.click(screen.getByRole("button", { name: "Скопировать" }));
    expect(await screen.findByText("Скопируйте ключ вручную")).toBeInTheDocument();
    expect(exec).toHaveBeenCalledWith("copy");
    expect(window.getSelection()?.toString()).toBe(ISSUED.token);
  });

  it("falls back to the old copy command and announces it", async () => {
    Object.assign(navigator, { clipboard: undefined });
    Object.assign(document, { execCommand: vi.fn().mockReturnValue(true) });
    api.getApiKey.mockResolvedValue(null);
    api.issueApiKey.mockResolvedValue(ISSUED);
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Выпустить ключ" }));
    await screen.findByText(ISSUED.token);
    fireEvent.click(screen.getByRole("button", { name: "Скопировать" }));
    expect(await screen.findAllByText("Скопировано")).not.toHaveLength(0);
    expect(screen.queryByText("Скопируйте ключ вручную")).toBeNull();
  });

  it("re-reads the key when a revoke finds it already gone", async () => {
    api.getApiKey.mockResolvedValueOnce(LIVE).mockResolvedValue(null);
    api.revokeApiKey.mockRejectedValue(new Error("404"));
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Отозвать" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, отозвать" }));
    expect(await screen.findByRole("button", { name: "Выпустить ключ" })).toBeInTheDocument();
  });

  it("re-reads the key when a reissue fails, and shows the top-up hint if not allowed", async () => {
    const { ApiKeyNotAllowedError } = await vi.importActual<typeof ApiKeyModule>("@/lib/api-key");
    api.getApiKey.mockResolvedValue(LIVE);
    api.issueApiKey.mockRejectedValue(new ApiKeyNotAllowedError());
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Перевыпустить" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, перевыпустить" }));
    expect(await screen.findByText("Сначала пополните баланс")).toBeInTheDocument();
    await waitFor(() => {
      expect(api.getApiKey.mock.calls.length).toBeGreaterThan(1);
    });
  });

  it("does not show the tariff", async () => {
    api.getApiKey.mockResolvedValue(LIVE);
    view();
    await screen.findByRole("button", { name: "Отозвать" });
    expect(screen.queryByText(/Тариф/)).toBeNull();
  });

  it("moves focus to the confirm button", async () => {
    api.getApiKey.mockResolvedValue(LIVE);
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Отозвать" }));
    expect(screen.getByRole("button", { name: "Да, отозвать" })).toHaveFocus();
  });

  it("shows «Любой адрес» for an empty allow-list", async () => {
    api.getApiKey.mockResolvedValue(LIVE);
    view();
    expect(await screen.findByText("Любой адрес")).toBeInTheDocument();
  });

  it("saves the lines as entries", async () => {
    api.getApiKey.mockResolvedValue(LIVE);
    api.setIpAllowlist.mockResolvedValue({ ...LIVE, ip_allowlist: ["203.0.113.7/32"] });
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Разрешённые IP-адреса" }), {
      target: { value: "203.0.113.7\n10.0.0.0/8" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.setIpAllowlist).toHaveBeenCalledWith(
        ["203.0.113.7", "10.0.0.0/8"],
        expect.stringMatching(/^web-apikey-/),
      );
    });
  });

  it("names the line the server refused", async () => {
    api.getApiKey.mockResolvedValue(LIVE);
    api.setIpAllowlist.mockRejectedValue(new IpAllowlistInvalidError(1));
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Разрешённые IP-адреса" }), {
      target: { value: "203.0.113.7\nnope" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Строка 2: не IP-адрес")).toBeInTheDocument();
  });
});
