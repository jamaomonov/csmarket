import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { BalanceView, type TransactionsType } from "@/components/balance/BalanceView";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const TYPES: readonly TransactionsType[] = ["topup", "withdrawal"];

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.transactions" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

/** «Транзакции»: per-account, so it renders client-side; `?type=topup|withdrawal` filters. */
export default async function TransactionsPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.transactions");
  const raw = (await searchParams).type;
  const type = TYPES.find((x) => x === raw) ?? "all";
  return (
    <main id="main-content" className="min-w-0 flex-1">
      <h1 className="mb-6 text-3xl font-bold">{t("title")}</h1>
      <BalanceView locale={locale} type={type} />
    </main>
  );
}
