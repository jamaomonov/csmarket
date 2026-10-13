import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { routing } from "@/i18n/routing";
import { loadWeapon, type WeaponData, weaponContent } from "@/lib/landing-content";
import { weaponPath } from "@/lib/paths";
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
  params: Promise<{ locale: string; weapon: string }>;
}

/*
 * Real 404s, as on the category page: an unknown weapon slug (or no facets) calls
 * `notFound()` in `generateMetadata` and in the page before anything streams; an API
 * outage throws into the error page (ruling Q10).
 */

/** The weapon behind the slug and its numbers; calls `notFound()` when the catalogue has none. */
async function load(locale: string, slug: string): Promise<WeaponData> {
  if (!hasLocale(routing.locales, locale)) notFound();
  const data = await loadWeapon(locale, slug);
  if (!data) notFound();
  return data;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, weapon: slug } = await params;
  const data = await load(locale, slug);
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const w = data.weapon.value;
  const title = t("landing.weaponTitle", { weapon: w });
  const description = data.from
    ? t("landing.description", {
        name: t("landing.skinsOf", { weapon: w }),
        items: t("landing.count", { unit: countUnit(undefined), count: data.weapon.count }),
        price: data.from,
        kind: "skin",
      })
    : t("meta.description");
  const path = weaponPath(slug);
  return {
    title,
    description,
    alternates: alternates(locale, path),
    other: GEO_META,
    robots: isThinLanding(data.weapon.count) ? NOINDEX_FOLLOW : ROBOTS,
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

export default async function SkinWeaponPage({ params }: Props) {
  const { locale, weapon: slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const data = await load(locale, slug);
  const c = await weaponContent(locale, data);
  return (
    <SkinLanding
      locale={locale}
      h1={c.h1}
      intro={c.intro}
      items={c.items}
      faq={{ title: (await getTranslations("web.skins"))("faq.title"), entries: c.faq }}
      allHref={c.allHref}
      crumbs={c.crumbs}
    />
  );
}
