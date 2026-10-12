// @vitest-environment jsdom
import en from "@csmarket/i18n/locales/en/web.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import uz from "@csmarket/i18n/locales/uz/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { PayConsent } from "./PayConsent";

const CATALOGUES = { ru, uz, en } as const;

function setup(locale: keyof typeof CATALOGUES, doc: "terms" | "sell") {
  render(
    <NextIntlClientProvider locale={locale} messages={{ web: CATALOGUES[locale] }}>
      <PayConsent doc={doc} />
    </NextIntlClientProvider>,
  );
}

describe("PayConsent", () => {
  it("links the public offer inside the sentence before a payment", () => {
    setup("ru", "terms");
    const link = screen.getByRole("link", { name: "публичной оферты" });
    expect(link).toHaveAttribute("href", "/legal/terms");
    expect(link.closest("p")).toHaveTextContent(
      "Оплачивая, вы принимаете условия публичной оферты.",
    );
  });

  it("links the buyback terms before a sale", () => {
    setup("ru", "sell");
    const link = screen.getByRole("link", { name: "условия выкупа" });
    expect(link).toHaveAttribute("href", "/legal/sell");
    expect(link.closest("p")).toHaveTextContent("Нажимая «Продать», вы принимаете условия выкупа.");
  });

  it.each(["uz", "en"] as const)("has a linked sentence in %s", (locale) => {
    setup(locale, "terms");
    expect(screen.getByRole("link")).toHaveAttribute("href", "/legal/terms");
  });
});
