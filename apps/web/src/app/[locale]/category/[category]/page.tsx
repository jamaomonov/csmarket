import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { routing } from "@/i18n/routing";
import { type CategoryData, categoryContent, loadCategory } from "@/lib/landing-content";
import { categoryPath } from "@/lib/paths";
import {
  alternates,
  GEO_META,
  localeUrl,
  NOINDEX_FOLLOW,
  ogLocale,
  ROBOTS,
  shareImage,
} from "@/lib/seo";
import { countUnit, isThinLanding, landingKind } from "@/lib/skin-landing";

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
async function load(locale: string, category: string): Promise<CategoryData> {
  if (!hasLocale(routing.locales, locale)) notFound();
  const data = await loadCategory(locale, category);
  if (!data) notFound();
  return data;
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
        kind: landingKind(data.category),
      })
    : t("meta.description");
  const path = categoryPath(category);
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

export default async function SkinCategoryPage({ params }: Props) {
  const { locale, category } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const data = await load(locale, category);
  const c = await categoryContent(locale, data);
  return (
    <SkinLanding
      locale={locale}
      h1={c.h1}
      intro={c.intro}
      items={c.items}
      faq={{ title: (await getTranslations("web.skins"))("faq.title"), entries: c.faq }}
      {...(c.text !== null && {
        after: <p className="text-fg-muted text-body mt-8 max-w-3xl leading-relaxed">{c.text}</p>,
      })}
      allHref={c.allHref}
      crumbs={c.crumbs}
      {...(c.links && { links: c.links })}
    />
  );
}
