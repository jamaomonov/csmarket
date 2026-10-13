/**
 * What a category or weapon landing says, built once for both its HTML page and its Markdown
 * twin for AI agents (`app/md`): the heading, the line of live numbers, the popular items, the
 * FAQ answered from those numbers, the category's paragraph and its weapon links.
 * `null` from a loader means the catalogue does not have it (the page answers 404).
 */
import { skinQueryString, type SkinItem } from "@csmarket/utils/skins";
import { getTranslations } from "next-intl/server";

import type { FaqEntry } from "@/lib/skin-seo";

import { categoryPath, MARKET, weaponPath } from "@/lib/paths";
import { countUnit, findWeapon, isSkinCategory, landingKind, weaponSlug } from "@/lib/skin-landing";
import { displayPrice, getSkinFacets, getSkinsPage } from "@/lib/skins";

/** Categories with a paragraph of their own (`seoPages.cat.text.<category>`). */
const TEXT_LIST = ["knives", "gloves", "rifles", "pistols", "cases", "agents"] as const;
type TextCategory = (typeof TEXT_LIST)[number];
const TEXT_CATEGORIES = new Set<string>(TEXT_LIST);

export interface Crumb {
  name: string;
  /** Locale-less path (`/category/knives`). */
  path: string;
}

export interface LandingContent {
  h1: string;
  intro: string | null;
  items: SkinItem[];
  faq: FaqEntry[];
  /** The category's own paragraph, if it has one. */
  text: string | null;
  links: { title: string; items: { label: string; path: string; count: number }[] } | null;
  crumbs: Crumb[];
  /** The same set in the filtered catalogue (locale-less). */
  allHref: string;
}

/** The category and its numbers; `null` when the catalogue does not have it. */
export async function loadCategory(locale: string, category: string) {
  if (!isSkinCategory(category)) return null;
  const [all, scoped, cheapest] = await Promise.all([
    getSkinFacets(),
    getSkinFacets(category),
    getSkinsPage({ sort: "price", category }),
  ]);
  const facet = all?.categories.find((c) => c.value === category);
  if (!facet || !scoped) return null;
  const first = cheapest.items[0] ?? null;
  const from = first ? displayPrice(locale, first.price_uzs, first.price_usd) : null;
  return { category, facet, scoped, from, cheapest: first };
}

export type CategoryData = NonNullable<Awaited<ReturnType<typeof loadCategory>>>;

/** The weapon behind the slug and its numbers; `null` when the catalogue has none. */
export async function loadWeapon(locale: string, slug: string) {
  const facets = await getSkinFacets();
  const weapon = facets ? findWeapon(facets, slug) : null;
  if (!weapon) return null;
  const cheapest = await getSkinsPage({ sort: "price", weapon: weapon.value });
  const first = cheapest.items[0];
  const from = first ? displayPrice(locale, first.price_uzs, first.price_usd) : null;
  const category = first && isSkinCategory(first.category) ? first.category : null;
  return { slug, weapon, from, category };
}

export type WeaponData = NonNullable<Awaited<ReturnType<typeof loadWeapon>>>;

export async function categoryContent(locale: string, data: CategoryData): Promise<LandingContent> {
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const tSeo = await getTranslations({ locale, namespace: "web.seoPages.cat" });
  const cat = data.category;
  const name = t(`category.${cat}`);
  const query = { sort: "popular" as const, category: cat };
  const page = await getSkinsPage(query);
  const items = t("landing.count", { unit: countUnit(cat), count: data.facet.count });
  const inline =
    cat === "agents"
      ? t("landing.agentsInline")
      : t("landing.categoryInline", { name: name.toLocaleLowerCase(locale) });
  // Questions buyers type, answered from the page's live numbers.
  const faq: FaqEntry[] = [
    ...(data.from
      ? [
          {
            question: tSeo("priceQ", { name: name.toLocaleLowerCase(locale) }),
            answer: tSeo("priceA", { price: data.from, items }),
          },
        ]
      : []),
    // "самый дешёвый нож в кс2" is how buyers ask; the answer is live, not written.
    ...(cat === "knives" && data.cheapest && data.from
      ? [
          {
            question: t("landing.cheapestKnifeQ"),
            answer: t("landing.cheapestKnifeA", {
              name: data.cheapest.name.replace(/^★\s*/, ""),
              price: data.from,
              items,
            }),
          },
        ]
      : []),
    { question: tSeo("howQ", { inline }), answer: tSeo("howA") },
  ];
  const seen = new Set<string>();
  const weapons = data.scoped.weapons.flatMap((w) => {
    const path = weaponPath(weaponSlug(w.value));
    if (seen.has(path)) return [];
    seen.add(path);
    return [{ label: w.value, path, count: w.count }];
  });
  const h1 = t("landing.categoryH1", { name });
  return {
    h1,
    intro: data.from
      ? t("landing.intro", { items, price: data.from, kind: landingKind(cat) })
      : null,
    items: page.items,
    faq,
    text: TEXT_CATEGORIES.has(cat) ? tSeo(`text.${cat as TextCategory}`) : null,
    links: { title: t("landing.weapons"), items: weapons },
    crumbs: [
      { name: t("market"), path: MARKET },
      { name: h1, path: categoryPath(cat) },
    ],
    allHref: MARKET + skinQueryString(query),
  };
}

export async function weaponContent(locale: string, data: WeaponData): Promise<LandingContent> {
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const tSeo = await getTranslations({ locale, namespace: "web.seoPages.cat" });
  const w = data.weapon.value;
  const query = {
    sort: "popular" as const,
    weapon: w,
    ...(data.category ? { category: data.category } : {}),
  };
  const page = await getSkinsPage(query);
  const items = t("landing.count", { unit: countUnit(undefined), count: data.weapon.count });
  // The category page's questions, asked about the weapon and answered from live numbers.
  const skinsOf = t("landing.skinsOf", { weapon: w });
  const faq: FaqEntry[] = [
    ...(data.from
      ? [
          {
            question: tSeo("priceQ", { name: skinsOf }),
            answer: tSeo("priceA", { price: data.from, items }),
          },
        ]
      : []),
    { question: tSeo("howQ", { inline: skinsOf }), answer: tSeo("howA") },
  ];
  const h1 = t("landing.weaponH1", { weapon: w });
  return {
    h1,
    intro: data.from ? t("landing.intro", { items, price: data.from, kind: "skin" }) : null,
    items: page.items,
    faq,
    text: null,
    links: null,
    crumbs: [
      { name: t("market"), path: MARKET },
      ...(data.category
        ? [
            {
              name: t("landing.categoryH1", { name: t(`category.${data.category}`) }),
              path: categoryPath(data.category),
            },
          ]
        : []),
      { name: h1, path: weaponPath(data.slug) },
    ],
    allHref: MARKET + skinQueryString(query),
  };
}
