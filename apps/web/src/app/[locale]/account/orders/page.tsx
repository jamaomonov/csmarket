import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { OrdersList } from "@/components/account/OrdersList";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.orders" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

/** «Мои заказы»: per-account, so the list renders client-side. */
export default async function OrdersPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.orders");
  return (
    <main id="main-content" className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-bold">{t("title")}</h1>
      <div className="mt-6">
        <OrdersList locale={locale} />
      </div>
    </main>
  );
}
