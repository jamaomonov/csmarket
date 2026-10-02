import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { OrderView } from "@/components/order/OrderView";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string; number: string }>;
}

/*
 * The page an order's buyer comes back to — from the buy panel (`?go=1` opens the
 * chosen kassa once) and, on a phone, from the bank app by hand. Everything about the
 * order is per-account, so the body renders client-side; an unknown number says so
 * there rather than calling `notFound()` (and so this route has no `loading.tsx`).
 */

export async function generateMetadata({ params }: Props) {
  const { locale, number } = await params;
  const t = await getTranslations({ locale, namespace: "web.orders" });
  return { title: t("number", { number }), robots: { index: false, follow: false } };
}

export default async function OrderPage({ params }: Props) {
  const { locale, number } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  return (
    <main id="main-content" className="mx-auto max-w-2xl px-6 py-10">
      <OrderView locale={locale} number={number} />
    </main>
  );
}
