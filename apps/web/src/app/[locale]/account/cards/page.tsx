import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CardsList } from "@/components/account/CardsList";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.cards" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

/** «Мои карты»: per-account, so it renders client-side. */
export default async function CardsPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.cards");
  return (
    <main id="main-content" className="min-w-0 flex-1">
      <h1 className="mb-6 text-3xl font-bold">{t("title")}</h1>
      <CardsList locale={locale} />
    </main>
  );
}
