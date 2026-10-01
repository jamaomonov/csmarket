import { Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import type { Metadata } from "next";

import { getPathname } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

import "./globals.css";

const sans = Inter({
  subsets: ["latin", "cyrillic"],
  variable: "--app-font-sans",
  display: "swap",
});
const mono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  variable: "--app-font-mono",
  display: "swap",
});

type AppLocale = (typeof routing.locales)[number];

/** The middleware tags every request with its locale (bare paths are `ru`). */
async function requestLocale(): Promise<AppLocale> {
  const locale = await getLocale();
  return routing.locales.find((l) => l === locale) ?? routing.defaultLocale;
}

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("web.notFound");
  return {
    title: t("title"),
    robots: { index: false, follow: false },
    icons: { icon: "/favicon.svg" },
  };
}

/**
 * Every unmatched path (`/en/foo`, `/uz/a/b`, `/xx`) ends here: the `[locale]`
 * layout does not wrap it, so this page brings its own `<html>`, in the
 * visitor's language.
 */
export default async function NotFound() {
  const locale = await requestLocale();
  const t = await getTranslations("web.notFound");
  const common = await getTranslations("common");
  return (
    <html
      lang={locale === "uz" ? "uz-Latn" : locale}
      className={`${sans.variable} ${mono.variable}`}
    >
      <body>
        <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center px-6 text-center">
          <p className="text-accent font-mono text-6xl font-bold">404</p>
          <h1 className="mt-4 text-2xl font-bold">{t("title")}</h1>
          <p className="text-fg-muted mt-3">{t("subtitle")}</p>
          <Link
            href={getPathname({ locale, href: "/" })}
            className="bg-accent text-accent-fg mt-8 rounded-md px-5 py-3 font-semibold"
          >
            {common("actions.home")}
          </Link>
        </main>
      </body>
    </html>
  );
}
