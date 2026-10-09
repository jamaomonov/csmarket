import { ChevronRight } from "lucide-react";
import { getTranslations } from "next-intl/server";

import type { FaqEntry } from "@/lib/skin-seo";
import type { SkinItem } from "@csmarket/utils/skins";

import { JsonLd } from "@/components/JsonLd";
import { SkinCard } from "@/components/skins/SkinCard";
import { SkinFaq } from "@/components/skins/SkinFaq";
import { Link } from "@/i18n/navigation";
import { localeUrl } from "@/lib/seo";
import { itemListLd } from "@/lib/skin-seo";

interface Crumb {
  name: string;
  /** Locale-less path (`/category/knives`). */
  path: string;
}

interface Props {
  locale: string;
  h1: string;
  intro: string | null;
  items: SkinItem[];
  /** The same set in the filtered catalogue, where paging and filters live (locale-less). */
  allHref: string;
  crumbs: Crumb[];
  /** Weapon pages to link to (a category's weapons). */
  links?: { title: string; items: { label: string; path: string; count: number }[] };
  /** Questions answered from the page's own numbers, shown last and as FAQPage JSON-LD. */
  faq?: { title: string; entries: FaqEntry[] };
}

/**
 * A CS2 landing page — a category («Ножи КС2 (CS2)») or a weapon («Скины AK-47 КС2 (CS2)»):
 * the heading, a line of real numbers (how many, from what price), the most popular 48, a
 * link into the filtered catalogue for the rest, and links to the pages beneath it.
 * Breadcrumbs and the shown skins (ItemList) as JSON-LD.
 */
export async function SkinLanding({
  locale,
  h1,
  intro,
  items,
  allHref,
  crumbs,
  links,
  faq,
}: Props) {
  const t = await getTranslations("web.skins");
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: c.name,
      item: localeUrl(locale, c.path),
    })),
  };
  const listLd = itemListLd(locale, items);
  const parents = crumbs.slice(0, -1);
  const current = crumbs.at(-1);
  return (
    <main id="main-content" className="mx-auto max-w-[1320px] px-4 pb-28 pt-6 sm:px-6">
      <JsonLd data={breadcrumbLd} />
      {listLd && <JsonLd data={listLd} />}
      <nav
        aria-label="breadcrumb"
        className="text-fg-dim mb-4 flex flex-wrap items-center gap-1 text-[13px]"
      >
        {parents.map((c) => (
          <span key={c.path} className="flex items-center gap-1">
            <Link href={c.path} className="hover:text-fg">
              {c.name}
            </Link>
            <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          </span>
        ))}
        {current && (
          <span aria-current="page" className="text-fg-muted">
            {current.name}
          </span>
        )}
      </nav>
      <h1 className="font-sans text-2xl font-bold md:text-3xl">{h1}</h1>
      {intro && <p className="text-fg-muted mt-2 max-w-2xl text-[14px]">{intro}</p>}

      {links && links.items.length > 0 && (
        <section className="mt-5">
          <h2 className="sr-only">{links.title}</h2>
          <ul className="flex flex-wrap gap-2">
            {links.items.map((l) => (
              <li key={l.path}>
                <Link
                  href={l.path}
                  className="border-border hover:border-border-strong inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] font-semibold"
                >
                  {l.label}
                  <span className="text-fg-dim tabular-nums">{l.count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <ul className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {items.map((item) => (
          <li key={item.slug}>
            <SkinCard item={item} locale={locale} />
          </li>
        ))}
      </ul>
      <Link
        href={allHref}
        className="border-border hover:border-border-strong mx-auto mt-6 block w-fit rounded-xl border px-6 py-3 font-semibold"
      >
        {t("landing.all")}
      </Link>
      {faq && <SkinFaq title={faq.title} entries={faq.entries} />}
    </main>
  );
}
