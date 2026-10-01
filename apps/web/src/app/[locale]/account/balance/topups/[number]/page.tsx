import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { TopupStatus } from "@/components/balance/TopupStatus";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string; number: string }>;
}

/*
 * The page a top-up's customer comes back to — from the form (`?go=1` opens the kassa
 * once) and, on a phone, from the bank app by hand. Everything about the top-up is
 * per-account, so the body renders client-side; an unknown number says so there rather
 * than calling `notFound()`.
 */

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.balance" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

export default async function TopupPage({ params }: Props) {
  const { locale, number } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  return (
    <main id="main-content" className="mx-auto max-w-2xl px-6 py-10">
      <TopupStatus locale={locale} number={number} />
    </main>
  );
}
