import { useTranslations } from "next-intl";

import type { ArticleLocales, ArticlesPage, Section } from "@/lib/articles";

import { ArticleCard } from "@/components/articles/ArticleCard";
import { Link } from "@/i18n/navigation";
import { SECTIONS, sectionHref } from "@/lib/articles";

interface ArticleListProps {
  locale: string;
  section: Section | null;
  page: ArticlesPage;
  sections: ArticleLocales;
}

/** «Статьи» or one section: the tabs (only sections with articles), the cards, «Показать ещё». */
export function ArticleList({ locale, section, page, sections }: ArticleListProps) {
  const t = useTranslations("web.articles");
  const live = Object.entries(sections).find(([l]) => l === locale)?.[1] ?? [];
  const tabs: (Section | null)[] = [null, ...SECTIONS.filter((s) => live.includes(s))];
  const here = sectionHref(section);
  return (
    <main
      id="main-content"
      className="mx-auto flex max-w-[1100px] flex-col gap-6 px-4 py-8 sm:px-6"
    >
      <h1 className="text-h2 font-semibold tracking-tight">
        {section ? t(`sectionTitles.${section}`) : t("heading")}
      </h1>
      {tabs.length > 2 ? (
        <nav aria-label={t("heading")} className="flex flex-wrap gap-2">
          {tabs.map((s) => (
            <Link
              key={s ?? "all"}
              href={sectionHref(s)}
              aria-current={s === section ? "page" : undefined}
              className="border-border aria-[current=page]:bg-accent aria-[current=page]:text-accent-fg rounded-full border px-4 py-1.5 text-sm"
            >
              {t(`sections.${s ?? "all"}`)}
            </Link>
          ))}
        </nav>
      ) : null}
      {page.items.length === 0 ? (
        <p className="text-fg-muted">{t("empty")}</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {page.items.map((a, i) => (
            <ArticleCard key={a.slug} article={a} locale={locale} priority={i < 3} />
          ))}
        </div>
      )}
      {page.next_cursor !== null ? (
        <Link
          href={`${here}?cursor=${encodeURIComponent(page.next_cursor)}`}
          className="border-border self-center rounded-lg border px-5 py-2 text-sm"
        >
          {t("more")}
        </Link>
      ) : null}
    </main>
  );
}
