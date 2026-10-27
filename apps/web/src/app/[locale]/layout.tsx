import { IBM_Plex_Mono, Onest } from "next/font/google";
import { notFound } from "next/navigation";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";
import { preconnect } from "react-dom";

import type { Metadata } from "next";

import { Analytics } from "@/components/Analytics";
import { Header } from "@/components/Header";
import { Providers } from "@/components/Providers";
import { RefCapture } from "@/components/referral/RefCapture";
import { routing } from "@/i18n/routing";
import { sectionsIn } from "@/lib/articles";
import { fetchArticleLocales } from "@/lib/articles-server";
import { clientMessages } from "@/lib/legal";
import { SITE } from "@/lib/site";

import "../globals.css";

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

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const t = await getTranslations("web.meta");
  return {
    metadataBase: new URL(SITE),
    title: { default: t("title"), template: "%s — csmarket" },
    description: t("description"),
    icons: {
      // Google wants a square favicon in a multiple of 48 px, Yandex and older tools ask for
      // /favicon.ico; browsers that can take the SVG prefer it.
      icon: [
        { url: "/favicon.ico", sizes: "48x48" },
        { url: "/favicon.svg", type: "image/svg+xml" },
        { url: "/icon-96.png", type: "image/png", sizes: "96x96" },
      ],
      apple: "/apple-touch-icon.png",
    },
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const messages = clientMessages(await getMessages());
  const articles = sectionsIn(await fetchArticleLocales(), locale).length > 0;
  // Skin pictures come from Steam's CDN: open the connection before the first <img> asks.
  preconnect("https://community.fastly.steamstatic.com");
  return (
    <html
      lang={locale === "uz" ? "uz-Latn" : locale}
      className={`${sans.variable} ${mono.variable}`}
    >
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Providers>
            <Header locale={locale} articles={articles} />
            {children}
          </Providers>
        </NextIntlClientProvider>
        <Analytics />
        <RefCapture />
      </body>
    </html>
  );
}
