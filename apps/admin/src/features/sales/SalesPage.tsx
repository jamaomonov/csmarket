/**
 * «Продажи»: attention `Tabs` (`?attention=`; «Ждут проверки» — the sales an admin has not marked
 * «Проверено» yet, its counter counts them all), a status `FilterSelect` and a search by number,
 * newest first.
 */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  ATTENTION_FILTERS,
  type AdminSaleRow,
  type AdminSalesPage,
  type AttentionFilter,
  listSales,
  SALE_STATUSES,
} from "./api";
import { SALES_LIST_KEY } from "./keys";

import { DataTable } from "@/components/DataTable";
import { FilterSelect, FiltersBar, SearchBox } from "@/components/Filters";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { SkinThumb } from "@/components/SkinThumb";
import { Status } from "@/components/Status";
import { Tabs } from "@/components/Tabs";
import { TextLink } from "@/components/TextLink";
import { UserCell } from "@/components/UserCell";
import { When } from "@/components/When";
import { errorText } from "@/features/users/labels";
import { reasonText, statusText } from "@/lib/dictionary";
import { pick, upTo } from "@/lib/url-guards";
import { useDebounced } from "@/lib/useDebounced";
import { useNarrow } from "@/lib/useNarrow";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;

type View = "all" | AttentionFilter;
const VIEWS: readonly View[] = ["all", "open", "resolved", "any"];
/** On a phone the tab counting work comes first. */
const PHONE_VIEWS: readonly View[] = ["open", "all", "resolved", "any"];
const VIEW_LABELS: Record<View, string> = {
  all: "Все",
  open: "Ждут проверки",
  resolved: "Проверены",
  any: "С пометкой",
};

/** The sale's dearest skin and «+N» for the rest. */
function FirstSkin({ sale }: { sale: AdminSaleRow }) {
  const first = sale.first_item ?? null;
  if (first === null) return <span className="text-fg-dim">—</span>;
  const rest = (sale.items_count ?? 1) - 1;
  return (
    <div className="flex min-w-0 items-center gap-2" data-testid="sale-first-skin">
      <SkinThumb url={first.image_url} />
      <span className="min-w-0 truncate">{first.name}</span>
      {rest > 0 && <span className="text-fg-muted shrink-0 text-xs">+{rest}</span>}
    </div>
  );
}

export function SalesPage() {
  const narrow = useNarrow();
  const navigate = useNavigate();
  const url = useUrlParams();
  const status = pick(SALE_STATUSES, url.get("status"));
  const attention = pick(ATTENTION_FILTERS, url.get("attention"));
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
    queryKey: [...SALES_LIST_KEY, status ?? "", q, attention ?? ""],
    queryFn: ({ pageParam }) =>
      listSales({
        ...(status ? { status } : {}),
        ...(attention ? { attention } : {}),
        ...(q ? { q } : {}),
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = query.data?.pages.flatMap((p) => p.items);
  const open = query.data?.pages[0]?.attention_open ?? 0;
  return (
    <section className="space-y-4">
      <PageHeader title="Продажи" />
      <Tabs<View>
        label="Пометка"
        value={attention ?? "all"}
        onChange={(v) => {
          url.set("attention", v === "all" ? "" : v);
        }}
        items={(narrow ? PHONE_VIEWS : VIEWS).map((v) => ({
          key: v,
          label: VIEW_LABELS[v],
          ...(v === "open" && query.data !== undefined && { count: open }),
          alert: v === "open",
        }))}
      />
      <FiltersBar>
        <SearchBox label="Номер продажи" value={text} maxLength={8} onChange={setText} />
        <FilterSelect
          label="Статус"
          value={status ?? ""}
          options={SALE_STATUSES}
          text={(s) => statusText("sale", s)}
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
        attention={(s) => s.attention_open}
        onRowClick={(s) => {
          void navigate(`/sales/${s.number}`);
        }}
        columns={[
          {
            key: "number",
            header: "Номер",
            cell: (s) => (
              <TextLink to={`/sales/${s.number}`} number>
                {s.number}
              </TextLink>
            ),
          },
          { key: "skins", header: "Скины", cell: (s) => <FirstSkin sale={s} /> },
          {
            key: "status",
            header: "Статус",
            cell: (s) => (
              <>
                <Status of="sale" code={s.status} />
                {s.attention_reason ? (
                  <div className={s.attention_open ? "text-danger text-xs" : "text-fg-dim text-xs"}>
                    {reasonText("saleAttention", s.attention_reason)}
                    {s.attention_open ? "" : " · проверено"}
                  </div>
                ) : null}
              </>
            ),
          },
          {
            key: "user",
            header: "Пользователь",
            cell: (s) => (
              <UserCell id={s.user.id} name={s.user.display_name} avatarUrl={s.user.avatar_url} />
            ),
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
            cell: (s) => <When iso={s.created_at} className="text-fg-muted" />,
          },
        ]}
        mobileCard={(s) => (
          <div className="space-y-1 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono">{s.number}</span>
              <Money uzs={s.payout_uzs} />
            </div>
            <FirstSkin sale={s} />
            <div className="flex flex-wrap gap-2">
              <Status of="sale" code={s.status} />
              <span className="text-fg-muted">{s.user.display_name ?? "Без имени"}</span>
              <When iso={s.created_at} className="text-fg-dim ml-auto text-xs" />
            </div>
            {s.attention_reason ? (
              <div className={s.attention_open ? "text-danger text-xs" : "text-fg-dim text-xs"}>
                {reasonText("saleAttention", s.attention_reason)}
                {s.attention_open ? "" : " · проверено"}
              </div>
            ) : null}
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
