import { ChevronRight } from "lucide-react";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { LegalShell } from "@/components/legal/LegalShell";
import { Link } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { LEGAL_DOCS } from "@/lib/legal";
import { LEGAL, legalPath } from "@/lib/paths";
import { alternates, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";

interface Props {
  params: Promise<{ locale: string }>;
}

/*
 * «Документы»: one address for all of them — the one handed to a kassa during onboarding or
 * pasted into a support reply. Each entry opens with the document's own lead paragraph.
 */

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const t = await getTranslations({ locale, namespace: "legal" });
  const title = t("index.title");
  const description = t("index.intro");
  return {
    title,
    description,
    alternates: alternates(locale, LEGAL),
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, LEGAL),
      ...ogLocale(locale),
    },
  };
}

export default async function LegalIndexPage({ params }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "legal" });
  return (
    <LegalShell locale={locale} title={t("index.title")} intro={t("index.intro")} isDoc={false}>
      <ul className="mt-8 flex flex-col gap-3">
        {LEGAL_DOCS.map((doc) => (
          <li key={doc}>
            <Link
              href={legalPath(doc)}
              className="border-border bg-surface hover:border-border-strong hover:bg-surface-hover group flex items-start gap-4 rounded-xl border p-4"
            >
              <span className="min-w-0 flex-1">
                <span className="text-title block font-bold">{t(`${doc}.title`)}</span>
                <span className="text-fg-muted text-body mt-1 block leading-relaxed">
                  {t(`${doc}.intro`)}
                </span>
              </span>
              <ChevronRight
                className="text-fg-dim group-hover:text-fg mt-1 h-4 w-4 shrink-0"
                aria-hidden
              />
            </Link>
          </li>
        ))}
      </ul>
    </LegalShell>
  );
}
