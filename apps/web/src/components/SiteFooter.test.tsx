// @vitest-environment jsdom
import ruLegal from "@csmarket/i18n/locales/ru/legal.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: ({ namespace }: { namespace: string }) =>
    Promise.resolve(
      createTranslator({
        locale: "ru",
        messages: { web: ru, legal: ruLegal },
        namespace: namespace as "web",
      }),
    ),
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { SiteFooter } from "./SiteFooter";

describe("SiteFooter", () => {
  it("has the Telegram column the home page has, opening outside the site", async () => {
    render(await SiteFooter({ locale: "ru" }));
    const nav = screen.getByRole("navigation", { name: "Telegram" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://t.me/cs2marketuz",
      "https://t.me/csmarketuz_chat",
      "https://t.me/jama_omonov",
    ]);
    for (const a of links) expect(a).toHaveAttribute("rel", "noopener noreferrer");
  });
});
