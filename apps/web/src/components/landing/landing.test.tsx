// @vitest-environment jsdom
import en from "@csmarket/i18n/locales/en/web.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import uz from "@csmarket/i18n/locales/uz/web.json";
import { render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

const MESSAGES = { ru, uz, en } as const;

vi.mock("next-intl/server", () => ({
  getTranslations: ({ locale, namespace }: { locale: "ru" | "uz" | "en"; namespace: string }) =>
    // The real catalogue for the asked namespace; the test passes namespaces as plain strings.
    Promise.resolve(
      createTranslator({
        locale,
        messages: { web: MESSAGES[locale] },
        namespace: namespace as "web",
      }),
    ),
  setRequestLocale: () => undefined,
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: unknown; children: React.ReactNode }) => (
    <a href={typeof href === "string" ? href : JSON.stringify(href)} {...rest}>
      {children}
    </a>
  ),
  getPathname: ({ href, locale }: { href: string; locale: string }) =>
    locale === "ru" ? href : `/${locale}${href}`,
}));

import { faqJsonLd, Faq } from "./Faq";
import { Hero } from "./Hero";
import { SearchBlock } from "./SearchBlock";

import type { SkinItem } from "@csmarket/utils/skins";

const knife: SkinItem = {
  slug: "karambit-fade-factory-new",
  name: "★ Karambit | Fade (Factory New)",
  phase: null,
  category: "knives",
  weapon: "Karambit",
  skin: "Fade",
  exterior: "FN",
  stattrak: false,
  souvenir: false,
  rarity: "Covert",
  rarity_color: "#eb4b4b",
  image_url: "https://community.fastly.steamstatic.com/economy/image/abc",
  price_usd: "1700",
  price_uzs: "21312000",
  steam_price_usd: null,
  discount_percent: null,
  count: 2,
  min_float: null,
  max_float: null,
};

describe("landing", () => {
  it("one H1 with the geo keyword, the CTAs to /market and /sell", async () => {
    render(await Hero({ items: [knife], locale: "ru" }));
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("Скины КС2 (CS2) в Узбекистане");
    expect(screen.getByRole("link", { name: /Открыть маркет/ })).toHaveAttribute("href", "/market");
    expect(screen.getByRole("link", { name: "Продать скины" })).toHaveAttribute("href", "/sell");
    expect(screen.getByRole("link", { name: /Купить/ })).toHaveAttribute(
      "href",
      "/item/karambit-fade-factory-new",
    );
  });

  it("an empty showcase (API down) leaves the copy and drops the stage", async () => {
    const { container } = render(await Hero({ items: [], locale: "ru" }));
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(container.querySelector(".stage")).toBeNull();
  });

  it("search submits to the locale's market", async () => {
    render(await SearchBlock({ locale: "uz" }));
    const form = screen.getByRole("search");
    expect(form).toHaveAttribute("action", "/uz/market");
    expect(form).toHaveAttribute("method", "get");
    expect(within(form).getByRole("searchbox")).toHaveAttribute("name", "q");
  });

  it("quick chips link weapons to their indexable pages", async () => {
    render(await SearchBlock({ locale: "ru" }));
    expect(screen.getByRole("link", { name: "AK-47" })).toHaveAttribute("href", "/weapon/ak-47");
    expect(screen.getByRole("link", { name: "Butterfly Knife" })).toHaveAttribute(
      "href",
      "/weapon/butterfly-knife",
    );
  });

  it("the FAQ JSON-LD lists exactly the visible questions", async () => {
    const { container } = render(await Faq({ locale: "ru" }));
    const questions = [...container.querySelectorAll("summary")].map((s) => s.textContent);
    const script = container.querySelector('script[type="application/ld+json"]');
    const ld = JSON.parse(script?.innerHTML ?? "{}") as {
      "@type": string;
      mainEntity: { name: string }[];
    };
    expect(ld["@type"]).toBe("FAQPage");
    expect(ld.mainEntity.map((q) => q.name)).toEqual(questions);
    expect(questions).toHaveLength(7);
  });

  it("the FAQ promises Telegram only once the link is set", async () => {
    vi.stubEnv("CSMARKET_TELEGRAM_URL", "");
    const { container, unmount } = render(await Faq({ locale: "ru" }));
    expect(container).not.toHaveTextContent("Telegram");
    unmount();
    vi.stubEnv("CSMARKET_TELEGRAM_URL", "https://t.me/csmarket_uz");
    render(await Faq({ locale: "ru" }));
    expect(screen.getByRole("link", { name: /Telegram/ })).toHaveAttribute(
      "href",
      "https://t.me/csmarket_uz",
    );
    vi.unstubAllEnvs();
  });

  it("faqJsonLd maps questions and answers", () => {
    expect(faqJsonLd([{ q: "Q?", a: "A." }])).toMatchObject({
      mainEntity: [{ "@type": "Question", name: "Q?", acceptedAnswer: { text: "A." } }],
    });
  });

  it("the Uzbek landing copy is Latin script only", () => {
    const text = JSON.stringify(uz.landing);
    expect(text).not.toMatch(/[А-Яа-яЁё]/);
  });

  it("every locale has the same FAQ and SEO-text length", () => {
    for (const m of [uz, en]) {
      expect(m.landing.faq.items).toHaveLength(ru.landing.faq.items.length);
      expect(m.landing.about.blocks).toHaveLength(ru.landing.about.blocks.length);
    }
  });
});
