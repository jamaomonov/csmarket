import { HandCoins } from "lucide-react";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { SellConfig } from "@/lib/sell";

import { ComingSoon } from "@/components/ComingSoon";
import { SellView } from "@/components/sell/SellView";
import { routing } from "@/i18n/routing";
import { apiGet } from "@/lib/server-api";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.nav" });
  return { title: t("sell"), robots: { index: false, follow: true } };
}

/** The switches as the API reports them now; `null` when it cannot say (then «Скоро»). */
async function sellConfig(): Promise<SellConfig | null> {
  try {
    return await apiGet<SellConfig>("/sell/config", { noStore: true });
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
    </main>
  );
}
