import { hasWear, isVanilla } from "@csmarket/utils/skins";
import { ChevronRight } from "lucide-react";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { SkinBuyPanel } from "@/components/skins/SkinBuyPanel";
import { SkinFaq } from "@/components/skins/SkinFaq";
import { SkinHero } from "@/components/skins/SkinHero";
import { SkinItemTitle } from "@/components/skins/SkinItemTitle";
import { SkinListings } from "@/components/skins/SkinListings";
import { SkinOffersProvider } from "@/components/skins/SkinOffers";
import { SkinPriceBlock } from "@/components/skins/SkinPriceBlock";
import { SkinSimilar } from "@/components/skins/SkinSimilar";
import { SkinWearPicker } from "@/components/skins/SkinWearPicker";
import { Link } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { itemOgUrl } from "@/lib/og-item";
import { categoryPath, MARKET, itemPath, weaponPath } from "@/lib/paths";
import {
  alternates,
  GEO_META,
  localeUrl,
  NOINDEX_FOLLOW,
  ogLocale,
  ROBOTS,
  shareImageAt,
} from "@/lib/seo";
import { isSkinCategory, weaponSlug } from "@/lib/skin-landing";
import { itemKind, skinAbout, skinFaq, skinFullName, skinProductLd } from "@/lib/skin-seo";
import { similarSkins } from "@/lib/skin-similar";
import { displayPrice, getSkinDetail } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string; slug: string }>;
}

const steamMarketUrl = (name: string) =>
  `https://steamcommunity.com/market/listings/730/${encodeURIComponent(name)}`;

/*
 * Real 404s. An unknown or hidden slug calls `notFound()` here and in the page, before
 * anything streams: no `loading.tsx` above this route (guarded by
 * `app/no-loading-boundaries.test.ts`) and no `<Suspense>` before the existence check, so
 * Next answers with status 404, not a 200 around a not-found body. An API outage is not a
 * 404: `getSkinDetail` throws and `[locale]/error.tsx` takes over.
 */

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const item = await getSkinDetail(slug);
  if (!item) notFound();
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const name = skinFullName(item);
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  // "купить X в Узбекистане за 40 000 сум": the query people type. No price, no "от —":
  // the copy drops the price rather than print a hole.
  const title =
    price !== null ? t("meta.itemTitle", { name, price }) : t("meta.itemTitleNoPrice", { name });
  const kind = itemKind(item);
  const description =
    price !== null && item.count > 0
      ? t("meta.itemDescription", { name, price, count: item.count, kind })
      : t("meta.itemDescriptionNoPrice", { name, kind });
  const path = itemPath(slug);
  // The generated card (`og.png/route.tsx`): the skin on the site's dark, no price on it.
  const share = shareImageAt(itemOgUrl(locale, slug), name);
  return {
    // No «— csmarket» suffix: item titles are long already, and the name must not be cut.
    title: { absolute: title },
    description,
    alternates: alternates(locale, path),
    other: GEO_META,
    // Nothing to buy, nothing to rank: an empty item page stays out of the index (its links
    // to the other wears and similar items are still followed) and comes back when stocked.
    robots: item.count > 0 ? ROBOTS : NOINDEX_FOLLOW,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, path),
      images: share.openGraph,
      ...ogLocale(locale),
    },
    twitter: share.twitter,
  };
}

export default async function SkinPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const item = await getSkinDetail(slug);
  if (!item) notFound();
  const t = await getTranslations("web.skins");
  const neighbours = await similarSkins(item);

  const name = isVanilla(item) ? t("vanilla") : (item.skin ?? item.name);
  const category = isSkinCategory(item.category) ? t(`category.${item.category}`) : item.category;
  // Weapon items hang under their weapon's landing, the rest under their category's.
  const parent = item.weapon
    ? { label: item.weapon, path: weaponPath(weaponSlug(item.weapon)) }
    : { label: category, path: categoryPath(item.category) };
  const floatRange =
    item.min_float !== null && item.max_float !== null
      ? `${Number(item.min_float).toFixed(2)}–${Number(item.max_float).toFixed(2)}`
      : null;
  const worn = hasWear(item.category);
  const url = localeUrl(locale, itemPath(item.slug));
  const about = skinAbout(item, t, locale, category);
  const productLd = skinProductLd(item, url, about);
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: t("market"), item: localeUrl(locale, MARKET) },
      {
        "@type": "ListItem",
        position: 2,
        name: parent.label,
        item: localeUrl(locale, parent.path),
      },
      { "@type": "ListItem", position: 3, name: skinFullName(item), item: url },
    ],
  };
  // The other wears and the facts: under the picture on wide screens, under the price on
  // phones — one copy, placed by the grid (a second copy would repeat its heading and text).
  const details = (
    <>
      {worn && item.family.length > 1 && (
        <div className="space-y-2">
          <h2 className="text-[15px] font-bold">{t("otherWears")}</h2>
          <SkinWearPicker family={item.family} current={item} locale={locale} />
        </div>
      )}
      <dl className="border-border grid grid-cols-2 gap-x-6 gap-y-2 border-t pt-4 text-[13px] sm:grid-cols-3">
        {item.exterior && <Fact label={t("wear")} value={t(`exterior.${item.exterior}`)} />}
        {item.rarity && (
          <Fact
            label={t("rarity")}
            value={item.rarity}
            {...(item.rarity_color ? { color: item.rarity_color } : {})}
          />
        )}
        {worn && floatRange && <Fact label={t("float")} value={floatRange} />}
        {!worn && item.count > 0 && (
          <Fact label={t("inStock")} value={t("pieces", { count: item.count })} />
        )}
        {item.collection && <Fact label={t("collection")} value={item.collection} />}
        {item.crates.length > 0 && (
          <div>
            <dt className="text-fg-dim text-[12px]">{t("cases")}</dt>
            <dd className="font-semibold">
              {item.crates.map((c, i) => (
                <span key={c.name}>
                  {i > 0 && ", "}
                  {c.slug ? (
                    <Link
                      href={itemPath(c.slug)}
                      className="hover:text-accent underline-offset-2 hover:underline"
                    >
                      {c.name}
                    </Link>
                  ) : (
                    c.name
                  )}
                </span>
              ))}
            </dd>
          </div>
        )}
      </dl>
    </>
  );

  return (
    <main id="main-content" className="mx-auto max-w-[1320px] px-4 pb-28 pt-6 sm:px-6">
      {productLd && <JsonLd data={productLd} />}
      <JsonLd data={breadcrumbLd} />
      <nav
        aria-label="breadcrumb"
        className="text-fg-dim mb-4 flex flex-wrap items-center gap-1 text-[13px]"
      >
        <Link href={MARKET} className="hover:text-fg">
          {t("market")}
        </Link>
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        <Link href={parent.path} className="hover:text-fg">
          {parent.label}
        </Link>
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        <span aria-current="page" className="text-fg-muted">
          {skinFullName(item)}
        </span>
      </nav>

      <SkinOffersProvider slug={item.slug}>
        <section className="border-border bg-surface grid gap-6 rounded-2xl border p-4 sm:p-5 md:grid-cols-2 md:grid-rows-[auto_1fr] md:gap-x-8 md:gap-y-5 md:p-8">
          {/* Left: the cheapest offer on the picture; on wide screens the wears and facts
              fill the space under it. Right: name and price. On phones the order is the
              source order: picture → name and price → wears and facts. */}
          <div className="md:col-start-1 md:row-start-1">
            <SkinHero
              image={item.image_url}
              name={item.name}
              exterior={item.exterior}
              rarityColor={item.rarity_color}
            />
          </div>
          <div className="flex flex-col gap-5 md:col-start-2 md:row-span-2 md:row-start-1">
            <SkinItemTitle
              name={name}
              phase={item.phase}
              exterior={item.exterior ? t(`exterior.${item.exterior}`) : null}
              weapon={item.weapon}
              stattrak={item.stattrak}
              souvenir={item.souvenir}
              category={category}
            />
            <SkinPriceBlock
              storedUzs={item.price_uzs}
              storedUsd={item.price_usd}
              steamUsd={item.steam_price_usd}
              steamUrl={steamMarketUrl(item.name)}
              locale={locale}
            />
            {item.buy_enabled && <SkinBuyPanel slug={item.slug} locale={locale} />}
          </div>
          <div className="space-y-5 md:col-start-1 md:row-start-2">{details}</div>
        </section>

        {worn && (
          <section className="mt-8">
            <h2 className="mb-3 text-[17px] font-bold">
              {t("offers")}{" "}
              <span className="text-fg-dim text-[14px] tabular-nums">{item.count}</span>
            </h2>
            <SkinListings
              locale={locale}
              image={item.image_url}
              exterior={item.exterior}
              selectable={item.buy_enabled}
            />
          </section>
        )}
      </SkinOffersProvider>

      <SkinSimilar
        title={
          item.weapon
            ? t("similar.weapon", { weapon: item.weapon })
            : t("similar.category", { category })
        }
        items={neighbours}
        locale={locale}
        allHref={parent.path}
        allLabel={
          item.weapon
            ? t("similar.all", { weapon: item.weapon })
            : t("similar.allCategory", { category })
        }
      />

      <section className="mt-10 max-w-3xl" aria-labelledby="skin-about">
        <h2 id="skin-about" className="mb-2 text-[17px] font-bold">
          {t("about.title")}
        </h2>
        <p className="text-fg-muted text-[14px] leading-relaxed">{about}</p>
        {/* Valve's text exists in English only: it shows where the page is English. */}
        {locale === "en" && item.description && (
          <blockquote className="border-border text-fg-muted mt-4 whitespace-pre-line border-l-2 pl-4 text-[14px] italic leading-relaxed">
            <span className="text-fg-dim mb-1 block text-[12px] not-italic">
              {t("about.valve")}
            </span>
            {item.description}
          </blockquote>
        )}
      </section>

      <SkinFaq title={t("faq.title")} entries={skinFaq(item, t, locale)} />
    </main>
  );
}

function Fact({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <dt className="text-fg-dim text-[12px]">{label}</dt>
      <dd className="font-semibold" style={color ? { color } : undefined}>
        {value}
      </dd>
    </div>
  );
}
