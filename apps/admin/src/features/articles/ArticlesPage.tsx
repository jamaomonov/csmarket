/**
 * «Статьи» (spec 2026-10-26-articles «Admin»): every article, last edited first, with its
 * section, status, the languages readers see and the counters; filters by section and status.
 */
import { Badge, buttonVariants } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { Eye, Heart } from "lucide-react";
import { Link } from "react-router-dom";

import { type ArticleFilter, listArticles } from "./api";
import {
  articleErrorText,
  LOCALE_LABEL,
  SECTION_LABEL,
  SECTIONS,
  STATUS_LABEL,
  STATUSES,
} from "./labels";

import { EmptyState } from "@/components/EmptyState";
import { FilterSelect, FiltersBar } from "@/components/Filters";
import { PageHeader } from "@/components/PageHeader";
import { formatDateTime } from "@/lib/format";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

export const ARTICLES_KEY = ["admin", "articles"] as const;

export function ArticlesPage() {
  const url = useUrlParams();
  const filter: ArticleFilter = {
    section: pick(SECTIONS, url.get("section")) ?? "",
    status: pick(STATUSES, url.get("status")) ?? "",
  };
  const list = useQuery({
    queryKey: [...ARTICLES_KEY, "list", filter],
    queryFn: () => listArticles(filter),
  });
  return (
    <section className="space-y-4">
      <PageHeader
        title="Статьи"
        actions={
          <Link to="/articles/new" className={buttonVariants({ variant: "primary" })}>
            Новая статья
          </Link>
        }
      />
      <FiltersBar>
        <FilterSelect
          label="Раздел"
          value={filter.section}
          options={SECTIONS}
          text={(s) => SECTION_LABEL[s]}
          onChange={(v) => {
            url.set("section", v);
          }}
        />
        <FilterSelect
          label="Статус"
          value={filter.status}
          options={STATUSES}
          text={(s) => STATUS_LABEL[s]}
          onChange={(v) => {
            url.set("status", v);
          }}
        />
      </FiltersBar>
      {list.isError ? <EmptyState tone="danger">{articleErrorText(list.error)}</EmptyState> : null}
      {list.isSuccess && list.data.length === 0 ? <EmptyState>Статей нет.</EmptyState> : null}
      <ul className="flex flex-col gap-2">
        {list.data?.map((a) => (
          <li key={a.id} className="border-border bg-surface rounded-xl border p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Link to={`/articles/${a.id}`} className="font-medium hover:underline">
                {a.title || "Без названия"}
              </Link>
              <Badge tone="neutral">{SECTION_LABEL[a.section]}</Badge>
              <Badge tone={a.status === "published" ? "accent" : "neutral"}>
                {STATUS_LABEL[a.status]}
              </Badge>
              {a.live_locales.map((l) => (
                <Badge key={l} tone="neutral">
                  {LOCALE_LABEL[l]}
                </Badge>
              ))}
            </div>
            <div className="text-fg-muted mt-2 flex flex-wrap items-center gap-4 text-sm">
              <span>/{a.slug}</span>
              <span>обновлена {formatDateTime(a.updated_at)}</span>
              <span className="ml-auto flex items-center gap-1" title="Просмотры">
                <Eye className="size-4" aria-hidden />
                {a.views}
              </span>
              <span className="flex items-center gap-1" title="Лайки">
                <Heart className="size-4" aria-hidden />
                {a.likes}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
