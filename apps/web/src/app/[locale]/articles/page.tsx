import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { ArticleList } from "@/components/articles/ArticleList";
import { routing } from "@/i18n/routing";
import { listMetadata } from "@/lib/articles-seo";
import { fetchArticleLocales, fetchArticles } from "@/lib/articles-server";

interface Props {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ cursor?: string | string[] }>;
}

function cursorOf(raw: string | string[] | undefined): string | null {
  return typeof raw === "string" && raw ? raw : null;
}

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  return listMetadata(locale, null, cursorOf((await searchParams).cursor));
}

/** «Статьи»: every live article in this language, newest first. */
export default async function ArticlesPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const [page, sections] = await Promise.all([
    fetchArticles(locale, null, cursorOf((await searchParams).cursor)),
    fetchArticleLocales(),
  ]);
  return <ArticleList locale={locale} section={null} page={page} sections={sections} />;
}
