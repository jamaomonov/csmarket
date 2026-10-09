/** «Продажи»: find a sale by number, filter by status, newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { type AdminSalesPage, listSales, SALE_STATUSES } from "./api";
import { SALES_LIST_KEY } from "./keys";
import { ATTENTION_LABELS, SALE_LABELS } from "./labels";

import { DataTable } from "@/components/DataTable";
import { FilterSelect, FiltersBar, SearchBox } from "@/components/Filters";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { UserCell } from "@/components/UserCell";
import { errorText } from "@/features/users/labels";
import { formatDateTime } from "@/lib/format";
import { pick, upTo } from "@/lib/url-guards";
import { useDebounced } from "@/lib/useDebounced";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;

export function SalesPage() {
  const navigate = useNavigate();
  const url = useUrlParams();
  const status = pick(SALE_STATUSES, url.get("status"));
  const q = upTo(url.get("q"), 8);
  // The box writes the URL once typing settles, not on every key.
  const [text, setText] = useState(q);
  const typed = useDebounced(text.trim(), DEBOUNCE_MS);
  const { set } = url;
  useEffect(() => {
    if (typed !== q) set("q", typed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a settled edit writes the URL
  }, [typed]);

  const query = useInfiniteQuery<
    AdminSalesPage,
    Error,
    InfiniteData<AdminSalesPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...SALES_LIST_KEY, status ?? "", q],
    queryFn: ({ pageParam }) =>
      listSales({
        ...(status ? { status } : {}),
        ...(q ? { q } : {}),
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = query.data?.pages.flatMap((p) => p.items);
  return (
    <section className="space-y-4">
      <PageHeader title="Продажи" />
      <FiltersBar>
        <SearchBox label="Номер продажи" value={text} maxLength={8} mono onChange={setText} />
        <FilterSelect
          label="Статус"
          value={status ?? ""}
          options={SALE_STATUSES}
          text={(s) => SALE_LABELS[s]}
          onChange={(v) => {
            url.set("status", v);
          }}
        />
      </FiltersBar>
      <DataTable
        label="Продажи"
        rows={items}
        rowKey={(s) => s.number}
        loading={query.isPending}
        error={query.isError ? errorText(query.error) : undefined}
        empty="Продаж не нашли."
        attention={(s) => s.attention_reason !== null}
        onRowClick={(s) => {
          void navigate(`/sales/${s.number}`);
        }}
        columns={[
          {
            key: "number",
            header: "Номер",
            cell: (s) => (
              <Link to={`/sales/${s.number}`} className="font-mono font-medium hover:underline">
                {s.number}
              </Link>
            ),
          },
          {
            key: "status",
            header: "Статус",
            cell: (s) => (
              <>
                {SALE_LABELS[s.status]}
                {s.attention_reason ? (
                  <div className="text-danger text-xs">
                    {ATTENTION_LABELS[s.attention_reason] ?? s.attention_reason}
                  </div>
                ) : null}
              </>
            ),
          },
          {
            key: "user",
            header: "Пользователь",
            cell: (s) => <UserCell id={s.user.id} name={s.user.display_name} />,
          },
          {
            key: "quoted",
            header: "Skinslink",
            align: "right",
            cell: (s) => <Money usd={s.quoted_usd} />,
          },
          {
            key: "payout",
            header: "Выплата",
            align: "right",
            cell: (s) => <Money uzs={s.payout_uzs} />,
          },
          {
            key: "margin",
            header: "Маржа",
            align: "right",
            cell: (s) => <Money usd={s.margin_usd} />,
          },
          {
            key: "created",
            header: "Создана",
            cell: (s) => (
              <span className="text-fg-muted whitespace-nowrap">
                {formatDateTime(s.created_at)}
              </span>
            ),
          },
        ]}
        mobileCard={(s) => (
          <div className="space-y-1 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono">{s.number}</span>
              <Money uzs={s.payout_uzs} />
            </div>
            <div className="flex flex-wrap gap-2">
              <span>{SALE_LABELS[s.status]}</span>
              <span className="text-fg-muted">{s.user.display_name ?? "Без имени"}</span>
              <span className="text-fg-dim ml-auto text-xs">{formatDateTime(s.created_at)}</span>
            </div>
          </div>
        )}
        footer={
          query.hasNextPage ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              Показать ещё
            </Button>
          ) : undefined
        }
      />
    </section>
  );
}
