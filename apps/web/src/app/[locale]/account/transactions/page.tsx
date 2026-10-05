import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { TransactionsView } from "@/components/transactions/TransactionsView";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.transactions" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

/** «Транзакции»: per-account, so the lists render client-side; `?tab=balance` opens the history. */
export default async function TransactionsPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.transactions");
  const tab = (await searchParams).tab === "balance" ? "balance" : "purchases";
  return (
    <main id="main-content" className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="mb-6 text-2xl font-bold">{t("title")}</h1>
      <TransactionsView locale={locale} tab={tab} />
    </main>
  );
}
