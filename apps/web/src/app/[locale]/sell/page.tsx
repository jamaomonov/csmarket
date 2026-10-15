import { HandCoins } from "lucide-react";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { SellConfig } from "@/lib/sell";
import type { Metadata } from "next";

import { ComingSoon } from "@/components/ComingSoon";
import { SellGuide } from "@/components/sell/SellGuide";
import { SellView } from "@/components/sell/SellView";
import { routing } from "@/i18n/routing";
import { SELL } from "@/lib/paths";
import { alternates, GEO_META, localeUrl, ogLocale, ROBOTS, shareImage } from "@/lib/seo";
import { apiGet } from "@/lib/server-api";

interface Props {
  params: Promise<{ locale: string }>;
}

/**
 * Indexed while selling is on (the page then answers «как продать скины в Узбекистане»);
 * `noindex` while it is «Скоро» or the API cannot say.
 */
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const config = await sellConfig();
  if (!config?.enabled) {
    const nav = await getTranslations({ locale, namespace: "web.nav" });
    return { title: nav("sell"), robots: { index: false, follow: true } };
  }
  const t = await getTranslations({ locale, namespace: "web.sell.seo" });
  const title = t("title");
  const description = t("description");
  return {
    title,
    description,
    alternates: alternates(locale, SELL),
    robots: ROBOTS,
    other: GEO_META,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, SELL),
      ...ogLocale(locale),
      images: shareImage(locale, title).openGraph,
    },
    twitter: shareImage(locale, title).twitter,
  };
}

/** The switches as the API reports them now; `null` when it cannot say (then «Скоро»). */
async function sellConfig(): Promise<SellConfig | null> {
  try {
    return await apiGet<SellConfig>("/sell/config", { noStore: true, perVisitor: true });
  } catch {
    return null;
  }
}

/** «Продать скины»: the seller's inventory and the cart while selling is on, «Скоро» otherwise. */
export default async function SellPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const config = await sellConfig();
  if (!config?.enabled) {
    return <ComingSoon section="sell" icon={HandCoins} />;
  }
  return (
    <main id="main-content" className="mx-auto max-w-[1320px] px-4 py-8 sm:px-6">
      <SellView locale={locale} config={config} />
      <SellGuide locale={locale} />
    </main>
  );
}
