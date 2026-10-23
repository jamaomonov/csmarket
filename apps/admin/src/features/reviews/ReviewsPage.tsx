/**
 * «Отзывы» (spec 2026-10-23-reviews «Admin»): «Плохие N» (unresolved first), «Все», «Хорошие»;
 * filters by kind and language; the public page's switch on top.
 */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import { getReviews, type ReviewFilter, type ReviewsPage as Page } from "./api";
import { KIND_LABELS, KINDS, LOCALE_LABELS, LOCALES, TAB_LABELS, TABS } from "./labels";
import { ReviewRow } from "./ReviewRow";
import { ReviewsSettings } from "./ReviewsSettings";

import { EmptyState } from "@/components/EmptyState";
import { FilterSelect, FiltersBar } from "@/components/Filters";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { DASHBOARD_KEY } from "@/features/dashboard/keys";
import { errorText } from "@/features/users/labels";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

const LIST_KEY = ["admin", "reviews", "list"] as const;

export function ReviewsPage() {
  const url = useUrlParams();
  const qc = useQueryClient();
  const filter: ReviewFilter = {
    tab: pick(TABS, url.get("tab")) ?? "bad",
    kind: pick(KINDS, url.get("kind")) ?? "",
    locale: pick(LOCALES, url.get("locale")) ?? "",
  };
  const list = useInfiniteQuery<
    Page,
    Error,
    InfiniteData<Page, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...LIST_KEY, filter],
    queryFn: ({ pageParam }) => getReviews(filter, pageParam),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const pages = list.data?.pages;
  const items = pages?.flatMap((p) => p.items) ?? [];
  const badOpen = pages?.[0]?.bad_open;
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: LIST_KEY });
    void qc.invalidateQueries({ queryKey: DASHBOARD_KEY });
  };

  return (
    <section className="space-y-4">
      <PageHeader title="Отзывы" />
      <ReviewsSettings />
      <Tabs
        label="Отзывы"
        value={filter.tab}
        onChange={(v) => {
          url.set("tab", v === "bad" ? "" : v);
        }}
        items={TABS.map((key) => ({
          key,
          label: TAB_LABELS[key],
          ...(key === "bad" && badOpen !== undefined && { count: badOpen, alert: true }),
        }))}
      />
      <FiltersBar>
        <FilterSelect
          label="Тип"
          value={filter.kind}
          options={KINDS}
          text={(k) => KIND_LABELS[k]}
          onChange={(v) => {
            url.set("kind", v);
          }}
        />
        <FilterSelect
          label="Язык"
          value={filter.locale}
          options={LOCALES}
          text={(l) => LOCALE_LABELS[l]}
          onChange={(v) => {
            url.set("locale", v);
          }}
        />
      </FiltersBar>
      {list.isError ? <EmptyState tone="danger">{errorText(list.error)}</EmptyState> : null}
      {list.isSuccess && items.length === 0 ? (
        <EmptyState>
          {filter.tab === "bad" ? "Плохих отзывов нет — всё разобрано." : "Отзывов нет."}
        </EmptyState>
      ) : null}
      <ul className="flex flex-col gap-2">
        {items.map((r) => (
          <ReviewRow key={r.id} review={r} onChanged={refresh} />
        ))}
      </ul>
      {list.hasNextPage ? (
        <Button
          variant="secondary"
          disabled={list.isFetchingNextPage}
          onClick={() => {
            void list.fetchNextPage();
          }}
        >
          Показать ещё
        </Button>
      ) : null}
    </section>
  );
}
