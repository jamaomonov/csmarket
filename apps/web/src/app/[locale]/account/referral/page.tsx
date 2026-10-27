import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { PartnerView } from "@/components/referral/PartnerView";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.nav" });
  return { title: t("referral"), robots: { index: false, follow: false } };
}

/** «Реферал»: a partner's link, numbers and rewards; per-account, so it renders client-side. */
export default async function Page({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.referral");
  return (
    <main id="main-content" className="min-w-0 flex-1">
      <h1 className="text-h2 mb-6 font-semibold tracking-tight">{t("title")}</h1>
      <PartnerView locale={locale} />
    </main>
  );
}
