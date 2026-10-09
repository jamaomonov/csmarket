import en from "@csmarket/i18n/locales/en/web.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import uz from "@csmarket/i18n/locales/uz/web.json";
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
vi.mock("@/i18n/navigation", () => ({ Link: () => null, getPathname: () => "/market" }));

import { generateMetadata } from "./page";

const meta = (locale: string) => generateMetadata({ params: Promise.resolve({ locale }) });

describe("landing metadata", () => {
  it("geo title and description per locale, canonical at the locale root", async () => {
    const r = await meta("ru");
    expect((r.title as { absolute: string }).absolute).toContain("в Узбекистане");
    expect(r.description).toContain("Click");
    expect(r.alternates?.canonical).toBe("https://csmarket.uz/");
    const u = await meta("uz");
    expect((u.title as { absolute: string }).absolute).toContain("Oʻzbekistonda");
    expect(u.alternates?.canonical).toBe("https://csmarket.uz/uz");
    expect(u.alternates?.languages).toMatchObject({ "x-default": "https://csmarket.uz/" });
  });

  it("is indexable (the indexing gate lives at the edge)", async () => {
    expect((await meta("en")).robots).toMatchObject({ index: true, follow: true });
  });

  it("shares the locale's branded preview", async () => {
    const u = await meta("uz");
    expect(u.openGraph?.images).toEqual([
      expect.objectContaining({ url: "https://csmarket.uz/og/uz.jpg", width: 1200 }),
    ]);
    expect(u.twitter).toMatchObject({ card: "summary_large_image" });
  });
});
