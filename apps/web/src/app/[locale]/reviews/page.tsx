import { isLocale } from "@csmarket/i18n";
import { Star } from "lucide-react";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { PublicReviews } from "@/lib/reviews";
import type { Metadata } from "next";

import { ComingSoon } from "@/components/ComingSoon";
import { ReviewList } from "@/components/reviews/ReviewList";
import { ReviewsMore } from "@/components/reviews/ReviewsMore";
import { routing } from "@/i18n/routing";
import { REVIEWS } from "@/lib/paths";
import { alternates, GEO_META, localeUrl, ogLocale, ROBOTS, shareImage } from "@/lib/seo";
import { apiGet } from "@/lib/server-api";

interface Props {
  params: Promise<{ locale: string }>;
}

/** The first page as the API serves it now (5-minute data cache); `null` when it cannot say. */
async function firstPage(locale: string): Promise<PublicReviews | null> {
  try {
    return await apiGet<PublicReviews>(`/reviews?locale=${locale}`, {
      revalidate: 300,
      tags: ["reviews"],
    });
  } catch {
    return null;
  }
}

/** Indexed while the page is on; `noindex` while it is «Скоро» or the API cannot say. */
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const data = await firstPage(locale);
  if (!data?.enabled) {
    const nav = await getTranslations({ locale, namespace: "web.nav" });
    return { title: nav("reviews"), robots: { index: false, follow: true } };
  }
  const t = await getTranslations({ locale, namespace: "web.reviews.page" });
  const title = t("title");
  const description = t("description");
  return {
    title,
    description,
    alternates: alternates(locale, REVIEWS),
    robots: ROBOTS,
    other: GEO_META,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, REVIEWS),
      ...ogLocale(locale),
      images: shareImage(locale, title).openGraph,
    },
    twitter: shareImage(locale, title).twitter,
  };
}

/** «Отзывы»: «Скоро» while the admin switch is off; the published reviews when it is on. */
export default async function ReviewsPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const data = await firstPage(locale);
  if (!data?.enabled) return <ComingSoon section="reviews" icon={Star} />;
  const t = await getTranslations("web.reviews.page");
  return (
    <main id="main-content" className="mx-auto flex max-w-[960px] flex-col gap-4 px-4 py-8 sm:px-6">
      <h1 className="text-h2 font-semibold tracking-tight">{t("heading")}</h1>
      <p className="text-fg-muted">
        {/* the count only: an average of 4–5★ reviews would always read 4+ (ADR-0023) */}
        {data.count > 0 ? t("summary", { count: data.count }) : t("empty")}
      </p>
      <ReviewList items={data.items} locale={locale} />
      {data.next_cursor !== null ? (
        <ReviewsMore locale={isLocale(locale) ? locale : "ru"} cursor={data.next_cursor} />
      ) : null}
    </main>
  );
}
