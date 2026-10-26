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

const { fetchArticleLocales } = vi.hoisted(() => ({ fetchArticleLocales: vi.fn() }));
vi.mock("@/lib/articles-server", () => ({ fetchArticleLocales }));

import { SiteFooter } from "./SiteFooter";

describe("SiteFooter", () => {
  it("links «Статьи» only in a language that has articles", async () => {
    fetchArticleLocales.mockResolvedValue({ ru: ["tops"], uz: [], en: [] });
    const { unmount } = render(await SiteFooter({ locale: "ru" }));
    expect(screen.getByRole("link", { name: "Статьи" })).toHaveAttribute("href", "/articles");
    unmount();
    fetchArticleLocales.mockResolvedValue({ ru: [], uz: [], en: [] });
    render(await SiteFooter({ locale: "ru" }));
    expect(screen.queryByRole("link", { name: "Статьи" })).toBeNull();
  });

  it("has the Telegram column the home page has, opening outside the site", async () => {
    fetchArticleLocales.mockResolvedValue({ ru: [], uz: [], en: [] });
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
