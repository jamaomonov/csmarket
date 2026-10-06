import { HandCoins, Info } from "lucide-react";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ComingSoon } from "@/components/ComingSoon";
import { SellView } from "@/components/sell/SellView";
import { routing } from "@/i18n/routing";
import { demoInventory } from "@/lib/sell-demo";
import { getSkinsPage } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.nav" });
  return { title: t("sell"), robots: { index: false, follow: true } };
}

/**
 * «Продать скины». The sell API does not exist yet (owner, 2026-10-06): production shows
 * «Скоро»; dev shows the page on a demo inventory made of catalogue items, so it can be
 * seen and tried. Nothing on it can sell.
 */
export default async function SellPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  if (process.env.NODE_ENV === "production") {
    return <ComingSoon section="sell" icon={HandCoins} />;
  }
  const t = await getTranslations("web.sell");
  const page = await getSkinsPage({ sort: "-price" });
  return (
    <main id="main-content" className="mx-auto max-w-[1320px] px-4 py-8 sm:px-6">
      <p className="border-info/30 bg-info/10 text-info mb-6 flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm">
        <Info className="size-4 shrink-0" aria-hidden />
        {t("demo")}
      </p>
      <SellView locale={locale} inventory={demoInventory(page.items, new Date())} />
    </main>
  );
}
