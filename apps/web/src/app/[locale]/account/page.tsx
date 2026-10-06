import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ProfileView } from "@/components/account/ProfileView";
import { routing } from "@/i18n/routing";

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.account" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

/** «Профиль». */
export default async function ProfilePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.account");
  return (
    <main id="main-content" className="min-w-0 flex-1">
      <h1 className="mb-6 text-3xl font-bold">{t("title")}</h1>
      <ProfileView locale={locale} />
    </main>
  );
}
