/**
 * «Мои сделки»: the owner's own figures for a period, «Вывел себе», and the deals — filtered by
 * status chips and a search kept in the URL. Kept apart from the shop's numbers (spec
 * 2026-10-29-desk, v2 2026-10-31).
 */
import { Button, Chip } from "@csmarket/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { DESK_KEY } from "./api";
import { type Cursors, DealRowLink, fetchDeals, FILTER_KEYS, FILTERS } from "./DealList";
import { DeskSummary } from "./DeskSummary";
import { DeskError, RowsSkeleton, TAP } from "./Parts";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { pick, upTo } from "@/lib/url-guards";
import { useDebounced } from "@/lib/useDebounced";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;
const Q_MAX = 120;

export function DeskPage() {
  const url = useUrlParams();
  const filter = pick(FILTER_KEYS, url.get("status")) ?? "all";
  const q = upTo(url.get("q"), Q_MAX);
  // The box writes the URL once typing settles, not on every key.
  const [text, setText] = useState(q);
  const typed = useDebounced(text.trim(), DEBOUNCE_MS);
  const { set } = url;
  useEffect(() => {
    if (typed !== q) set("q", typed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a settled edit writes the URL
  }, [typed]);
  const statuses = FILTERS[filter].statuses;
  const deals = useInfiniteQuery({
    queryKey: [...DESK_KEY, "deals", filter, q],
    queryFn: ({ pageParam }) => fetchDeals(statuses, q, pageParam),
    initialPageParam: null as Cursors | null,
    getNextPageParam: (last) => last.next,
  });
  const rows = deals.data?.pages.flatMap((p) => p.items) ?? [];
  const newDeal = (
    <Link to="/desk/new">
      <Button className={TAP}>Новая сделка</Button>
    </Link>
  );
  return (
    <section className="space-y-4">
      <PageHeader
        title="Мои сделки"
        meta="Личные сделки с трейдерами — отдельно от цифр магазина."
        actions={
          <div className="flex gap-2">
            <Link to="/desk/stock">
              <Button variant="secondary" className={TAP}>
                Склад
              </Button>
            </Link>
            {newDeal}
          </div>
        }
      />
      <DeskSummary />
      <div className="space-y-3">
        <label className="flex max-w-sm flex-col gap-1 text-sm">
          Трейдер или скин
          <input
            type="search"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            placeholder="Ник или название скина"
            className="border-border bg-bg h-11 rounded-md border px-3"
          />
        </label>
        <div role="group" aria-label="Статус" className="-mx-4 flex gap-2 overflow-x-auto px-4">
          {FILTER_KEYS.map((k) => (
            <Chip
              key={k}
              active={k === filter}
              className={TAP}
              onClick={() => {
                set("status", k === "all" ? "" : k);
              }}
            >
              {FILTERS[k].label}
            </Chip>
          ))}
        </div>
      </div>
      {deals.isError && (
        <DeskError
          error={deals.error}
          onRetry={() => {
            void deals.refetch();
          }}
        />
      )}
      {deals.isPending && <RowsSkeleton />}
      {deals.isSuccess &&
        rows.length === 0 &&
        (q !== "" || filter !== "all" ? (
          <p className="text-fg-muted">Ничего не нашли{q !== "" && ` по «${q}»`}.</p>
        ) : (
          <EmptyState action={newDeal}>Сделок пока нет</EmptyState>
        ))}
      {rows.length > 0 && (
        <ul className="divide-border border-border divide-y rounded-lg border" aria-label="Сделки">
          {rows.map((d) => (
            <li key={d.id}>
              <DealRowLink d={d} />
            </li>
          ))}
        </ul>
      )}
      {deals.hasNextPage && (
        <Button
          variant="secondary"
          className={`w-full ${TAP}`}
          disabled={deals.isFetchingNextPage}
          onClick={() => {
            void deals.fetchNextPage();
          }}
        >
          {deals.isFetchingNextPage ? "Загружаем…" : "Показать ещё"}
        </Button>
      )}
    </section>
  );
}
