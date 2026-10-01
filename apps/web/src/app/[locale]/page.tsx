import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { routing } from "@/i18n/routing";

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.home");
  const common = await getTranslations("common");
  return (
    <main
      id="main-content"
      className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-2xl flex-col justify-center px-6 py-24"
    >
      <p className="text-fg-muted font-mono text-sm uppercase tracking-widest">{common("brand")}</p>
      <h1 className="mt-4 text-4xl font-bold tracking-tight sm:text-5xl">{t("title")}</h1>
      <p className="text-fg-muted mt-4 text-lg">{t("lead")}</p>
      <p className="text-accent mt-8 text-base font-semibold">{t("soon")}</p>
    </main>
  );
}
