import { skinQueryString } from "@csmarket/utils/skins";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { routing } from "@/i18n/routing";
import { categoryPath, MARKET, weaponPath } from "@/lib/paths";
import { alternates, GEO_META, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";
import { countUnit, isSkinCategory, weaponSlug } from "@/lib/skin-landing";
import { displayPrice, getSkinFacets, getSkinsPage } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string; category: string }>;
}

/*
 * Real 404s: an unknown category (or one the API has no facets for) calls `notFound()` in
 * `generateMetadata` and in the page, before anything streams — no `loading.tsx` above this
 * route and no `<Suspense>` before the check. An API outage is not a 404: the helpers throw
 * and `[locale]/error.tsx` takes over (ruling Q10).
 */

/** The category and its numbers; calls `notFound()` when the catalogue does not have it. */
async function load(locale: string, category: string) {
  if (!hasLocale(routing.locales, locale)) notFound();
  if (!isSkinCategory(category)) notFound();
  const [all, scoped, cheapest] = await Promise.all([
    getSkinFacets(),
    getSkinFacets(category),
    getSkinsPage({ sort: "price", category }),
  ]);
  const facet = all?.categories.find((c) => c.value === category);
  if (!facet || !scoped) notFound();
  const first = cheapest.items[0] ?? null;
  const from = first ? displayPrice(locale, first.price_uzs, first.price_usd) : null;
  return { category, facet, scoped, from, cheapest: first };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, category } = await params;
  const data = await load(locale, category);
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const name = t(`category.${data.category}`);
  const title = t("landing.categoryTitle", { name });
  const description = data.from
    ? t("landing.description", {
        // «Купить агентов», not «агенты»: the one animate noun among the categories.
        name:
          data.category === "agents"
            ? t("landing.agentsInline")
            : t("landing.categoryInline", { name: name.toLocaleLowerCase(locale) }),
        items: t("landing.count", { unit: countUnit(data.category), count: data.facet.count }),
        price: data.from,
      })
    : t("meta.description");
  const path = categoryPath(category);
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

export default async function SkinCategoryPage({ params }: Props) {
  const { locale, category } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const data = await load(locale, category);
  const t = await getTranslations("web.skins");
  const cat = data.category;
  const name = t(`category.${cat}`);
  const query = { sort: "popular" as const, category: cat };
  const page = await getSkinsPage(query);
  const items = t("landing.count", { unit: countUnit(cat), count: data.facet.count });
  // "самый дешёвый нож в кс2" is how buyers ask; the answer is live, not written.
  const faq =
    cat === "knives" && data.cheapest && data.from
      ? {
          title: t("faq.title"),
          entries: [
            {
              question: t("landing.cheapestKnifeQ"),
              answer: t("landing.cheapestKnifeA", {
                name: data.cheapest.name.replace(/^★\s*/, ""),
                price: data.from,
                items,
              }),
            },
          ],
        }
      : undefined;
  const seen = new Set<string>();
  const weapons = data.scoped.weapons.flatMap((w) => {
    const path = weaponPath(weaponSlug(w.value));
    if (seen.has(path)) return [];
    seen.add(path);
    return [{ label: w.value, path, count: w.count }];
  });
  return (
    <SkinLanding
      locale={locale}
      h1={t("landing.categoryH1", { name })}
      intro={data.from ? t("landing.intro", { items, price: data.from }) : null}
      items={page.items}
      {...(faq ? { faq } : {})}
      allHref={MARKET + skinQueryString(query)}
      crumbs={[
        { name: t("market"), path: MARKET },
        { name: t("landing.categoryH1", { name }), path: categoryPath(cat) },
      ]}
      links={{ title: t("landing.weapons"), items: weapons }}
    />
  );
}
