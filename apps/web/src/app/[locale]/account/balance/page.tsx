import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { BalanceView } from "@/components/balance/BalanceView";
import { routing } from "@/i18n/routing";

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.balance" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

export default async function BalancePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.balance");
  return (
    <main id="main-content" className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-bold">{t("title")}</h1>
      <div className="mt-6">
        <BalanceView locale={locale} />
      </div>
    </main>
  );
}
