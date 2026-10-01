// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SteamCallback } from "./SteamCallback";

const mocks = vi.hoisted(() => ({
  completeSteamSignIn: vi.fn<(params: Record<string, string>) => Promise<void>>(),
  replace: vi.fn(),
}));

// Like Next's own hook, the search params follow `history.replaceState`: after the
// callback strips the query, a re-render sees an empty one.
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/i18n/navigation", () => ({ useRouter: () => mocks }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    completeSteamSignIn: mocks.completeSteamSignIn,
    signInHref: (locale: string) =>
      `http://api.test/api/v1/auth/steam/start?app=web&locale=${locale}`,
  }),
}));

/** What Steam appends to our `return_to` (fake id, fake signature). */
const ASSERTION = {
  "openid.ns": "http://specs.openid.net/auth/2.0",
  "openid.mode": "id_res",
  "openid.claimed_id": "https://steamcommunity.com/openid/id/76561198000000001",
  "openid.identity": "https://steamcommunity.com/openid/id/76561198000000001",
  "openid.return_to": "http://localhost:3100/auth/steam/callback?locale=uz&n=fake-nonce",
  "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle",
  "openid.sig": "ZmFrZQ==",
};

function landOnCallback(locale: string): void {
  const query = new URLSearchParams({ locale, n: "fake-nonce", ...ASSERTION });
  window.history.replaceState(null, "", `/auth/steam/callback?${query.toString()}`);
}

function renderCallback() {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <SteamCallback />
    </NextIntlClientProvider>,
  );
}

describe("SteamCallback (web)", () => {
  beforeEach(() => {
    mocks.completeSteamSignIn.mockReset();
    mocks.replace.mockReset();
  });
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("forwards exactly the openid.* params and strips them from the address bar", async () => {
    mocks.completeSteamSignIn.mockResolvedValue(undefined);
    landOnCallback("uz");
    renderCallback();
    await waitFor(() => {
      expect(mocks.completeSteamSignIn).toHaveBeenCalledOnce();
    });
    expect(mocks.completeSteamSignIn).toHaveBeenCalledWith(ASSERTION);
    expect(window.location.search).toBe("");
    expect(window.location.pathname).toBe("/auth/steam/callback");
  });

  it("opens the account in the locale the sign-in started from", async () => {
    mocks.completeSteamSignIn.mockResolvedValue(undefined);
    landOnCallback("uz");
    renderCallback();
    await waitFor(() => {
      expect(mocks.replace).toHaveBeenCalledWith("/account", { locale: "uz" });
    });
  });

  it("offers a retry in the requested locale when the sign-in fails", async () => {
    mocks.completeSteamSignIn.mockRejectedValue(new Error("401"));
    landOnCallback("en");
    renderCallback();
    const retry = await screen.findByRole("link", { name: "Попробовать ещё раз" });
    expect(retry.getAttribute("href")).toBe(
      "http://api.test/api/v1/auth/steam/start?app=web&locale=en",
    );
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("falls back to the default locale for an unknown one", async () => {
    mocks.completeSteamSignIn.mockRejectedValue(new Error("401"));
    landOnCallback("de");
    renderCallback();
    const retry = await screen.findByRole("link", { name: "Попробовать ещё раз" });
    expect(retry.getAttribute("href")).toContain("locale=ru");
  });
});
