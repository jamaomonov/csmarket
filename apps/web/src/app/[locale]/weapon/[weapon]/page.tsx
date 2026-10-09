import { skinQueryString } from "@csmarket/utils/skins";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { routing } from "@/i18n/routing";
import { categoryPath, MARKET, weaponPath } from "@/lib/paths";
import { alternates, GEO_META, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";
import { countUnit, findWeapon, isSkinCategory } from "@/lib/skin-landing";
import { displayPrice, getSkinFacets, getSkinsPage } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string; weapon: string }>;
}

/*
 * Real 404s, as on the category page: an unknown weapon slug (or no facets) calls
 * `notFound()` in `generateMetadata` and in the page before anything streams; an API
 * outage throws into the error page (ruling Q10).
 */

/** The weapon behind the slug and its numbers; calls `notFound()` when the catalogue has none. */
async function load(locale: string, slug: string) {
  if (!hasLocale(routing.locales, locale)) notFound();
  const facets = await getSkinFacets();
  const weapon = facets ? findWeapon(facets, slug) : null;
  if (!weapon) notFound();
  const cheapest = await getSkinsPage({ sort: "price", weapon: weapon.value });
  const first = cheapest.items[0];
  const from = first ? displayPrice(locale, first.price_uzs, first.price_usd) : null;
  const category = first && isSkinCategory(first.category) ? first.category : null;
  return { weapon, from, category };
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
      })
    : t("meta.description");
  const path = weaponPath(slug);
  return {
    title,
    description,
    alternates: alternates(locale, path),
    other: GEO_META,
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, path),
      ...ogLocale(locale),
    },
  };
}

export default async function SkinWeaponPage({ params }: Props) {
  const { locale, weapon: slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const data = await load(locale, slug);
  const t = await getTranslations("web.skins");
  const w = data.weapon.value;
  const query = {
    sort: "popular" as const,
    weapon: w,
    ...(data.category ? { category: data.category } : {}),
  };
  const page = await getSkinsPage(query);
  const items = t("landing.count", { unit: countUnit(undefined), count: data.weapon.count });
  return (
    <SkinLanding
      locale={locale}
      h1={t("landing.weaponH1", { weapon: w })}
      intro={data.from ? t("landing.intro", { items, price: data.from }) : null}
      items={page.items}
      allHref={MARKET + skinQueryString(query)}
      crumbs={[
        { name: t("market"), path: MARKET },
        ...(data.category
          ? [
              {
                name: t("landing.categoryH1", { name: t(`category.${data.category}`) }),
                path: categoryPath(data.category),
              },
            ]
          : []),
        { name: t("landing.weaponH1", { weapon: w }), path: weaponPath(slug) },
      ]}
    />
  );
}
