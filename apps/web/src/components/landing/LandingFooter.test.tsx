// @vitest-environment jsdom
import enLegal from "@csmarket/i18n/locales/en/legal.json";
import en from "@csmarket/i18n/locales/en/web.json";
import ruLegal from "@csmarket/i18n/locales/ru/legal.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

const MESSAGES = { ru: { web: ru, legal: ruLegal }, en: { web: en, legal: enLegal } } as const;

vi.mock("next-intl/server", () => ({
  getTranslations: ({ locale, namespace }: { locale: "ru" | "en"; namespace: string }) =>
    // The real catalogue for the asked namespace; the test passes namespaces as plain strings.
    Promise.resolve(
      createTranslator({ locale, messages: MESSAGES[locale], namespace: namespace as "web" }),
    ),
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { LandingFooter } from "./LandingFooter";

describe("LandingFooter", () => {
  it("links every legal document by its title", async () => {
    render(await LandingFooter({ locale: "ru" }));
    const nav = screen.getByRole("navigation", { name: "Документы" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/legal/terms",
      "/legal/agreement",
      "/legal/sell",
      "/legal/privacy",
      "/legal/refunds",
      "/legal/imprint",
    ]);
    expect(within(nav).getByRole("link", { name: "Публичная оферта" })).toBeInTheDocument();
  });

  it("splits Telegram by purpose: channel, community, support", async () => {
    render(await LandingFooter({ locale: "ru" }));
    const nav = screen.getByRole("navigation", { name: "Telegram" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Новости и скидки", "https://t.me/cs2marketuz"],
      ["Сообщество", "https://t.me/csmarketuz_chat"],
      ["Поддержка", "https://t.me/jama_omonov"],
    ]);
  });

  it("speaks the page's language", async () => {
    render(await LandingFooter({ locale: "en" }));
    const nav = screen.getByRole("navigation", { name: "Documents" });
    expect(within(nav).getByRole("link", { name: "Privacy policy" })).toBeInTheDocument();
  });
});
