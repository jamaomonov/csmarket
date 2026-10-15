import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { LegalShell } from "@/components/legal/LegalShell";
import { routing } from "@/i18n/routing";
import { isLegalDoc, LEGAL_DOCS, type LegalDoc } from "@/lib/legal";
import { legalPath } from "@/lib/paths";
import { alternates, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";

interface Props {
  params: Promise<{ locale: string; doc: string }>;
}

interface Section {
  h: string;
  p: string;
}

/*
 * One legal document. «terms» (the offer) governs a purchase, «agreement» the use of the site,
 * «sell» selling skins to us — separate on purpose: a ban needs a published basis, and that
 * basis has no place in a contract about one item. Real 404 for any other slug, before
 * anything streams.
 */

export function generateStaticParams(): { doc: LegalDoc }[] {
  return LEGAL_DOCS.map((doc) => ({ doc }));
}

function docOf(locale: string, raw: string): LegalDoc {
  if (!hasLocale(routing.locales, locale) || !isLegalDoc(raw)) notFound();
  return raw;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, doc: raw } = await params;
  const doc = docOf(locale, raw);
  const t = await getTranslations({ locale, namespace: "legal" });
  const title = t(`${doc}.title`);
  const description = t(`${doc}.intro`);
  return {
    title,
    description,
    alternates: alternates(locale, legalPath(doc)),
    robots: ROBOTS,
    openGraph: {
      type: "article",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, legalPath(doc)),
      ...ogLocale(locale),
    },
  };
}

export default async function LegalDocPage({ params }: Props) {
  const { locale, doc: raw } = await params;
  const doc = docOf(locale, raw);
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "legal" });
  // The catalogue's own array of `{h, p}`: a known shape from our JSON, hence the cast.
  const sections = t.raw(`${doc}.sections`) as Section[];
  return (
    <LegalShell
      locale={locale}
      title={t(`${doc}.title`)}
      updated={t(`${doc}.updated`)}
      intro={t(`${doc}.intro`)}
      isDoc
    >
      <ol className="mt-8 flex flex-col gap-7">
        {sections.map((s, i) => (
          <li key={s.h}>
            <section aria-labelledby={`s${String(i + 1)}`}>
              <h2 id={`s${String(i + 1)}`} className="text-title font-bold">
                {i + 1}. {s.h}
              </h2>
              <p className="text-fg-muted text-lead mt-2 leading-relaxed">{s.p}</p>
            </section>
          </li>
        ))}
      </ol>
    </LegalShell>
  );
}
