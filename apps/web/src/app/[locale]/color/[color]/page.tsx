import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { routing } from "@/i18n/routing";
import { type ColorData, colorContent, loadColor } from "@/lib/landing-content";
import { colorPath } from "@/lib/paths";
import {
  alternates,
  GEO_META,
  localeUrl,
  NOINDEX_FOLLOW,
  ogLocale,
  ROBOTS,
  shareImage,
} from "@/lib/seo";
import { countUnit, isThinLanding } from "@/lib/skin-landing";

interface Props {
  params: Promise<{ locale: string; color: string }>;
}

/*
 * «Красные скины КС2 (CS2)» (spec 2026-10-14-skin-colors). Real 404s, as on the weapon page:
 * an unknown colour or one with no items calls `notFound()` in `generateMetadata` and in the
 * page before anything streams; an API outage throws into the error page.
 */

/** The colour and its numbers; calls `notFound()` when the catalogue has none of it. */
async function load(locale: string, color: string): Promise<ColorData> {
  if (!hasLocale(routing.locales, locale)) notFound();
  const data = await loadColor(locale, color);
  if (!data) notFound();
  return data;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, color } = await params;
  const data = await load(locale, color);
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const plural = t(`color.plural.${data.color}`);
  const title = t("color.metaTitle", { plural });
  const description = data.from
    ? t("landing.description", {
        name: t("color.inline", { plural }).toLocaleLowerCase(locale),
        items: t("landing.count", { unit: countUnit(undefined), count: data.facet.count }),
        price: data.from,
        kind: "skin",
      })
    : t("meta.description");
  const path = colorPath(data.color);
  return {
    title,
    description,
    alternates: alternates(locale, path),
    other: GEO_META,
    robots: isThinLanding(data.facet.count) ? NOINDEX_FOLLOW : ROBOTS,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, path),
      ...ogLocale(locale),
      images: shareImage(locale, title).openGraph,
    },
    twitter: shareImage(locale, title).twitter,
  };
}

export default async function SkinColorPage({ params }: Props) {
  const { locale, color } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const data = await load(locale, color);
  const c = await colorContent(locale, data);
  return (
    <SkinLanding
      locale={locale}
      h1={c.h1}
      intro={c.intro}
      items={c.items}
      faq={{ title: (await getTranslations("web.skins"))("faq.title"), entries: c.faq }}
      allHref={c.allHref}
      crumbs={c.crumbs}
      {...(c.links && { links: c.links })}
    />
  );
}
