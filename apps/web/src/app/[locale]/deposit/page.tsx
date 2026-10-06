import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { DepositView } from "@/components/deposit/DepositView";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.deposit" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

/** «Пополнение баланса»: per-account, so it renders client-side. */
export default async function DepositPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  return (
    <main id="main-content" className="mx-auto max-w-[1100px] px-4 py-8 sm:px-6">
      <DepositView locale={locale} />
    </main>
  );
}
