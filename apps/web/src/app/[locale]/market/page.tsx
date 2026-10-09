import { buttonVariants, Panel } from "@csmarket/ui";
import {
  activeFilterCount,
  isFilteredQuery,
  parseSkinQuery,
  skinQueryString,
} from "@csmarket/utils/skins";
import { SearchX, SlidersHorizontal } from "lucide-react";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinCard } from "@/components/skins/SkinCard";
import { SkinCategoryBar } from "@/components/skins/SkinCategoryBar";
import { SkinFilterDrawer } from "@/components/skins/SkinFilterDrawer";
import { SkinFilters } from "@/components/skins/SkinFilters";
import { SkinGridMore } from "@/components/skins/SkinGridMore";
import { SkinLandingLinks } from "@/components/skins/SkinLandingLinks";
import { SkinSearch } from "@/components/skins/SkinSearch";
import { SkinSort } from "@/components/skins/SkinSort";
import { Link } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { MARKET } from "@/lib/paths";
import { JsonLd } from "@/components/JsonLd";
import { alternates, GEO_META, NOINDEX_FOLLOW, ogLocale, ROBOTS } from "@/lib/seo";
import { itemListLd } from "@/lib/skin-seo";
import { getSkinFacets, getSkinsPage } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

/**
 * Reads `searchParams`, so Next renders it per request; the data helpers cache upstream
 * fetches themselves. Stated explicitly so a build never tries to prerender `/` against an API.
 */
export const dynamic = "force-dynamic";

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "web.skins" });
  // Only a recognised filter makes a duplicate of the hub (ruling Q9): utm_*, fbclid and
  // gclid are not in `SkinQuery`, so a tracked visit stays indexable.
  const filtered = isFilteredQuery(parseSkinQuery(await searchParams));
  const count = (await getSkinFacets())?.categories.reduce((sum, c) => sum + c.count, 0) ?? 0;
  return {
    title: t("meta.title"),
    description: count > 0 ? t("meta.marketDescription", { count }) : t("meta.description"),
    alternates: alternates(locale, MARKET),
    robots: filtered ? NOINDEX_FOLLOW : ROBOTS,
    openGraph: { type: "website", siteName: "csmarket", ...ogLocale(locale) },
    other: GEO_META,
  };
}

export default async function HomePage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const t = await getTranslations("web.skins");
  const query = parseSkinQuery(await searchParams);
  const filtered = isFilteredQuery(query);
  // An API outage throws into `[locale]/error.tsx`. Facets are `null` only for a category
  // the API does not know: the home page still renders, without the category bar (Q10).
  const [page, facets] = await Promise.all([getSkinsPage(query), getSkinFacets(query.category)]);
  // Only the indexable hub describes its list; a filtered view is noindex.
  const listLd = filtered ? null : itemListLd(locale, page.items);

  return (
    <main id="main-content" className="mx-auto max-w-[1320px] px-4 pb-28 pt-2 sm:px-6">
      {listLd && <JsonLd data={listLd} />}
      <h1 className="mb-5 text-center text-[26px] font-semibold">{t("title")}</h1>
      <div className="lg:flex lg:gap-3">
        {facets && (
          <aside className="hidden lg:block lg:w-[250px] lg:shrink-0">
            <Panel className="sticky top-4">
              <p className="mb-1 flex items-center gap-2 text-[17px] font-semibold">
                <SlidersHorizontal className="size-4" aria-hidden />
                {t("filters")}
              </p>
              <SkinFilters query={query} facets={facets} />
            </Panel>
          </aside>
        )}
        <section className="min-w-0 flex-1">
          <Panel className="mb-3 flex flex-col gap-2.5 p-3 sm:flex-row">
            <SkinSearch initial={query.q ?? ""} locale={locale} query={query} />
            <div className="flex gap-2">
              {facets && (
                <SkinFilterDrawer count={activeFilterCount(query)}>
                  <SkinFilters query={query} facets={facets} />
                </SkinFilterDrawer>
              )}
              <SkinSort query={query} />
            </div>
          </Panel>
          {facets && (
            <Panel className="p-2">
              <SkinCategoryBar query={query} facets={facets} />
            </Panel>
          )}
          {page.items.length === 0 ? (
            <div className="flex flex-col items-center gap-4 py-16 text-center">
              <SearchX className="text-fg-dim h-10 w-10" aria-hidden />
              <p className="text-fg-muted max-w-sm">{t("empty")}</p>
              <Link href={MARKET} className={buttonVariants({ variant: "secondary" })}>
                {t("resetFilters")}
              </Link>
            </div>
          ) : (
            <ul className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {page.items.map((item) => (
                <li key={item.slug}>
                  <SkinCard item={item} locale={locale} />
                </li>
              ))}
              {/* Later batches join this same grid, so a short last row fills up. */}
              {page.next_cursor && (
                <SkinGridMore
                  key={skinQueryString(query)}
                  query={query}
                  cursor={page.next_cursor}
                  locale={locale}
                  shown={page.items.map((i) => i.slug)}
                />
              )}
            </ul>
          )}
          {/* The unfiltered home links its landing pages; a filtered view is noindex anyway. */}
          {!filtered && facets && <SkinLandingLinks facets={facets} />}
        </section>
      </div>
    </main>
  );
}
