import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import "@/components/landing/landing.css";
import { JsonLd } from "@/components/JsonLd";
import { About } from "@/components/landing/About";
import { BuySell } from "@/components/landing/BuySell";
import { Categories } from "@/components/landing/Categories";
import { Faq } from "@/components/landing/Faq";
import { FinalCta } from "@/components/landing/FinalCta";
import { Hero } from "@/components/landing/Hero";
import { LandingFooter } from "@/components/landing/LandingFooter";
import { Popular } from "@/components/landing/Popular";
import { Reveal } from "@/components/landing/Reveal";
import { SearchBlock } from "@/components/landing/SearchBlock";
import { Stats } from "@/components/landing/Stats";
import { WhyUs } from "@/components/landing/WhyUs";
import { routing } from "@/i18n/routing";
import { getLandingData, socialUrls } from "@/lib/landing";
import { HOME, MARKET } from "@/lib/paths";
import { alternates, GEO_META, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";
import { SITE } from "@/lib/site";

interface Props {
  params: Promise<{ locale: string }>;
}

/**
 * Rendered per request (never prerendered at build, where no API answers); its data is one
 * 5-minute cache entry (`getLandingData`), so a render is cheap.
 */
export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "web.landing.meta" });
  return {
    title: { absolute: `${t("title")} | csmarket` },
    description: t("description"),
    alternates: alternates(locale, HOME),
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title: t("title"),
      description: t("description"),
      url: localeUrl(locale, HOME),
      ...ogLocale(locale),
    },
    other: GEO_META,
  };
}

/** `Organization` and `WebSite` with the sitelinks search box (→ /market?q=). */
function siteJsonLd(locale: string, description: string): object[] {
  return [
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: "csmarket",
      url: `${SITE}/`,
      logo: `${SITE}/favicon.svg`,
      description,
      areaServed: { "@type": "Country", name: "Uzbekistan" },
      ...(socialUrls().length > 0 && { sameAs: socialUrls() }),
    },
    {
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: "csmarket",
      url: localeUrl(locale, HOME),
      inLanguage: locale === "uz" ? "uz-Latn" : locale,
      potentialAction: {
        "@type": "SearchAction",
        target: {
          "@type": "EntryPoint",
          urlTemplate: `${localeUrl(locale, MARKET)}?q={search_term_string}`,
        },
        "query-input": "required name=search_term_string",
      },
    },
  ];
}

export default async function LandingPage({ params }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "web.landing.meta" });
  const { hero, tiles, stats, popular: lists } = await getLandingData();

  return (
    <div className="lp" id="lp">
      <main id="main-content">
        <Hero items={hero} locale={locale} />
        <SearchBlock locale={locale} />
        <Popular lists={lists} locale={locale} />
        <Stats stats={stats} locale={locale} />
        <Categories tiles={tiles} locale={locale} />
        <BuySell samples={lists.knives.length > 0 ? lists.knives : lists.popular} locale={locale} />
        <WhyUs locale={locale} />
        <Faq locale={locale} />
        <About locale={locale} />
        <FinalCta items={hero} locale={locale} />
      </main>
      <LandingFooter locale={locale} />
      {siteJsonLd(locale, t("description")).map((data, i) => (
        <JsonLd key={i} data={data} />
      ))}
      <Reveal rootId="lp" />
    </div>
  );
}
