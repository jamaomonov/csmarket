import { type SkinItem, skinQueryString } from "@csmarket/utils/skins";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { routing } from "@/i18n/routing";
import { CHEAP_MAX_UZS, CHEAP_MIX, getPopular } from "@/lib/landing";
import { CHEAP, MARKET } from "@/lib/paths";
import { alternates, GEO_META, localeUrl, ogLocale, ROBOTS, shareImage } from "@/lib/seo";
import { displayPrice, getSkinsPage } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string }>;
}

/** The filtered catalogue behind «Все с фильтрами». */
const ALL = { sort: "popular" as const, maxUzs: CHEAP_MAX_UZS };

/** Every item in the band is priced (the API filters by `max_uzs`); `""` never shows. */
const price = (locale: string, it: SkinItem): string =>
  displayPrice(locale, it.price_uzs, it.price_usd) ?? "";

/**
 * The band's cheapest weapon skin (`null` when there is none): the cheapest of each weapon
 * category, so a case or a key never answers «самый дешёвый скин». 404 for an unknown locale.
 */
async function cheapest(locale: string): Promise<SkinItem | null> {
  if (!hasLocale(routing.locales, locale)) notFound();
  const pages = await Promise.all(
    CHEAP_MIX.map((category) => getSkinsPage({ sort: "price", category, maxUzs: CHEAP_MAX_UZS })),
  );
  const firsts = pages.flatMap((p) => p.items.slice(0, 1));
  return firsts.reduce<SkinItem | null>(
    (min, it) => (min === null || Number(it.price_uzs) < Number(min.price_uzs) ? it : min),
    null,
  );
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const first = await cheapest(locale);
  const t = await getTranslations({ locale, namespace: "web.seoPages.cheap" });
  const title = t("title");
  const description = first
    ? t("description", { price: price(locale, first) })
    : t("descriptionNoPrice");
  return {
    title,
    description,
    alternates: alternates(locale, CHEAP),
    robots: ROBOTS,
    other: GEO_META,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, CHEAP),
      ...ogLocale(locale),
      images: shareImage(locale, title).openGraph,
    },
    twitter: shareImage(locale, title).twitter,
  };
}

/** «Дешёвые скины КС2 (CS2) до 100 000 сум»: the band, live answers from its own numbers. */
export default async function CheapPage({ params }: Props) {
  const { locale } = await params;
  const first = await cheapest(locale);
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "web.seoPages.cheap" });
  const tSkins = await getTranslations({ locale, namespace: "web.skins" });
  // The landing's «До 100 000 сум» tab: rifles, pistols and SMGs in turn, no cases or keys.
  const items = await getPopular("cheap");
  const top = items.slice(0, 3);
  const entries = [
    ...(first
      ? [
          {
            question: t("cheapestQ"),
            answer: t("cheapestA", { name: first.name, price: price(locale, first) }),
          },
        ]
      : []),
    ...(top.length > 0
      ? [
          {
            question: t("popularQ"),
            answer: t("popularA", {
              list: top.map((it) => `${it.name} — ${price(locale, it)}`).join(", "),
            }),
          },
        ]
      : []),
    { question: t("howQ"), answer: t("howA") },
  ];
  return (
    <SkinLanding
      locale={locale}
      h1={t("h1")}
      intro={first ? t("intro", { price: price(locale, first) }) : null}
      items={items}
      allHref={MARKET + skinQueryString(ALL)}
      crumbs={[
        { name: tSkins("market"), path: MARKET },
        { name: t("crumb"), path: CHEAP },
      ]}
      faq={{ title: tSkins("faq.title"), entries }}
    />
  );
}
