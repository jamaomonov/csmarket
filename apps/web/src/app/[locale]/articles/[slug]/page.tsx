import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Article, Section } from "@/lib/articles";
import type { Metadata } from "next";

import { ArticleList } from "@/components/articles/ArticleList";
import { ArticleView } from "@/components/articles/ArticleView";
import { JsonLd } from "@/components/JsonLd";
import { permanentRedirect } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { API_BASE } from "@/lib/api";
import { isSection, mediaPath } from "@/lib/articles";
import { listMetadata } from "@/lib/articles-seo";
import { fetchArticle, fetchArticleLocales, fetchArticles } from "@/lib/articles-server";
import { ARTICLES, articlePath } from "@/lib/paths";
import { alternatesFor, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";
import { SITE } from "@/lib/site";

interface Props {
  params: Promise<{ locale: string; slug: string }>;
  searchParams: Promise<{ cursor?: string | string[] }>;
}

/*
 * `/articles/<slug>` is one article, or a section list when the slug is `news` / `guides` /
 * `tops` (those words are refused as article slugs). A missing translation is a real 404:
 * `notFound()` runs before anything streams (no `loading.tsx` above this route).
 */

function cursorOf(raw: string | string[] | undefined): string | null {
  return typeof raw === "string" && raw ? raw : null;
}

async function load(slug: string, locale: string): Promise<Article> {
  const found = await fetchArticle(slug, locale);
  if (found?.kind === "article") return found;
  if (found?.kind === "redirect") permanentRedirect({ href: articlePath(found.slug), locale });
  notFound();
}

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  if (isSection(slug)) {
    return listMetadata(locale, slug, cursorOf((await searchParams).cursor));
  }
  const article = await load(slug, locale);
  const path = articlePath(article.slug);
  const image = API_BASE + mediaPath(article.cover.url);
  return {
    title: article.title,
    description: article.description,
    alternates: alternatesFor(locale, path, article.locales),
    robots: ROBOTS,
    openGraph: {
      type: "article",
      siteName: "csmarket",
      title: article.title,
      description: article.description,
      url: localeUrl(locale, path),
      publishedTime: article.published_at,
      modifiedTime: article.updated_at,
      ...ogLocale(locale),
      images: [
        {
          url: image,
          width: article.cover.width,
          height: article.cover.height,
          alt: article.cover_alt,
        },
      ],
    },
    twitter: { card: "summary_large_image", title: article.title, images: [image] },
  };
}

async function SectionPage({
  locale,
  section,
  cursor,
}: {
  locale: string;
  section: Section;
  cursor: string | null;
}) {
  const [page, sections] = await Promise.all([
    fetchArticles(locale, section, cursor),
    fetchArticleLocales(),
  ]);
  return <ArticleList locale={locale} section={section} page={page} sections={sections} />;
}

export default async function ArticlePage({ params, searchParams }: Props) {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  if (isSection(slug)) {
    return (
      <SectionPage locale={locale} section={slug} cursor={cursorOf((await searchParams).cursor)} />
    );
  }
  const article = await load(slug, locale);
  const t = await getTranslations("web.articles");
  const url = localeUrl(locale, articlePath(article.slug));
  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "Article",
          headline: article.title,
          description: article.description,
          image: [API_BASE + mediaPath(article.cover.url)],
          datePublished: article.published_at,
          dateModified: article.updated_at,
          inLanguage: locale,
          mainEntityOfPage: url,
          author: { "@type": "Organization", name: "csmarket", url: SITE },
          publisher: { "@type": "Organization", name: "csmarket", url: SITE },
        }}
      />
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            {
              "@type": "ListItem",
              position: 1,
              name: t("heading"),
              item: localeUrl(locale, ARTICLES),
            },
            {
              "@type": "ListItem",
              position: 2,
              name: t(`sections.${article.section}`),
              item: localeUrl(locale, articlePath(article.section)),
            },
            { "@type": "ListItem", position: 3, name: article.title, item: url },
          ],
        }}
      />
      <ArticleView article={article} locale={locale} />
    </>
  );
}
