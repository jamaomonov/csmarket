import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { SaleView } from "@/components/sale/SaleView";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string; number: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale, number } = await params;
  const t = await getTranslations({ locale, namespace: "web.sales" });
  return { title: t("number", { number }), robots: { index: false, follow: false } };
}

/** A sale's page: per-account, so the body renders client-side (an unknown number says so
 * there; no `notFound()`, so no `loading.tsx`). */
export default async function SalePage({ params }: Props) {
  const { locale, number } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  return (
    <main id="main-content" className="min-w-0 flex-1">
      <SaleView locale={locale} number={number} />
    </main>
  );
}
