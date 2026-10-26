import { ChevronRight } from "lucide-react";
import Image from "next/image";
import { useTranslations } from "next-intl";

import type { Article } from "@/lib/articles";

import { ArticleBody } from "@/components/articles/ArticleBody";
import { ArticleCard } from "@/components/articles/ArticleCard";
import { ArticleStats } from "@/components/articles/ArticleStats";
import { ViewBeacon } from "@/components/articles/ViewBeacon";
import { Link } from "@/i18n/navigation";
import { API_BASE } from "@/lib/api";
import { mediaPath, sectionHref } from "@/lib/articles";
import { ARTICLES } from "@/lib/paths";

interface ArticleViewProps {
  article: Article;
  locale: string;
}

/** One article: the breadcrumb, the title, dates and counters, the cover, the body, «Ещё в
 * разделе». */
export function ArticleView({ article, locale }: ArticleViewProps) {
  const t = useTranslations("web.articles");
  const date = new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric" });
  const updated = article.updated_at.slice(0, 10) !== article.published_at.slice(0, 10);
  return (
    <main id="main-content" className="mx-auto flex max-w-[760px] flex-col gap-5 px-4 py-8 sm:px-6">
      <nav aria-label="breadcrumb" className="text-fg-muted flex items-center gap-1 text-sm">
        <Link href={ARTICLES} className="hover:text-fg">
          {t("heading")}
        </Link>
        <ChevronRight className="size-4" aria-hidden />
        <Link href={sectionHref(article.section)} className="hover:text-fg">
          {t(`sections.${article.section}`)}
        </Link>
      </nav>
      <h1 className="text-h2 font-semibold leading-tight tracking-tight">{article.title}</h1>
      <div className="text-fg-dim flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <time dateTime={article.published_at}>{date.format(new Date(article.published_at))}</time>
        {updated ? (
          <span>{t("updated", { date: date.format(new Date(article.updated_at)) })}</span>
        ) : null}
        <span>{t("author")}</span>
        <div className="ml-auto">
          <ArticleStats slug={article.slug} likes={article.likes} views={article.views} />
        </div>
      </div>
      <Image
        src={API_BASE + mediaPath(article.cover.url)}
        alt={article.cover_alt}
        width={article.cover.width}
        height={article.cover.height}
        sizes="(max-width: 768px) 100vw, 760px"
        className="h-auto w-full rounded-xl"
        priority
      />
      <ArticleBody article={article} locale={locale} />
      {article.related.length > 0 ? (
        <section className="mt-6 flex flex-col gap-4">
          <h2 className="text-xl font-semibold">{t("related")}</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {article.related.map((a) => (
              <ArticleCard key={a.slug} article={a} locale={locale} />
            ))}
          </div>
        </section>
      ) : null}
      <ViewBeacon slug={article.slug} />
    </main>
  );
}
