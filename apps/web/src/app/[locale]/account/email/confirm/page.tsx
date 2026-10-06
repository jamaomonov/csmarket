import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ConfirmEmail } from "@/components/account/ConfirmEmail";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.account.email.confirm" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

/** The link in a confirmation letter lands here; the client reads the token (M4b R7). */
export default async function ConfirmEmailPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.account.email.confirm");
  return (
    <main id="main-content" className="min-w-0 flex-1">
      <h1 className="text-2xl font-bold">{t("title")}</h1>
      <div className="mt-6">
        <ConfirmEmail />
      </div>
    </main>
  );
}
