import { IBM_Plex_Mono, Onest } from "next/font/google";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import type { Metadata } from "next";

import { getPathname } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { categoryPath, CHEAP, MARKET } from "@/lib/paths";

import "./globals.css";

const sans = Onest({
  subsets: ["latin", "latin-ext", "cyrillic"],
  weight: ["400", "500", "600", "700"],
  variable: "--app-font-sans",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin", "cyrillic"],
  weight: ["500"],
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
    icons: {
      icon: [
        { url: "/favicon.ico", sizes: "48x48" },
        { url: "/favicon.svg", type: "image/svg+xml" },
      ],
    },
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
  const tCat = await getTranslations("web.skins.category");
  const tSkins = await getTranslations("web.skins");
  const tBuy = await getTranslations("web.seoPages.footer");
  // Somewhere to go on from a dead link: the catalogue and its busiest sections.
  const links = [
    { href: MARKET, label: tSkins("market") },
    ...(["knives", "gloves", "rifles", "cases"] as const).map((c) => ({
      href: categoryPath(c),
      label: tCat(c),
    })),
    { href: CHEAP, label: tBuy("cheap") },
  ];
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
          <nav aria-label={tSkins("market")} className="mt-6">
            <ul className="text-fg-muted text-body flex flex-wrap justify-center gap-x-4 gap-y-2">
              {links.map((l) => (
                <li key={l.href}>
                  <Link href={getPathname({ locale, href: l.href })} className="hover:text-fg">
                    {l.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </main>
      </body>
    </html>
  );
}
