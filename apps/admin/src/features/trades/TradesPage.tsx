/** «Обмены»: every order as a trade — Waxpeer, Skinslink and LIS-SKINS, site and API — with
 * tabs, search by number, name or Steam offer id, and expandable rows. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  type AdminTradeCounts,
  type AdminTradesPage,
  listTrades,
  type ListTradesParams,
} from "./api";
import { TRADE_VIEWS, type TradeView } from "./kinds";
import { TRADE_VIEW_LABELS } from "./labels";
import { TradeCard, TradeLine } from "./TradeLine";
import { TRADES_KEY } from "../orders/keys";

import { EmptyState } from "@/components/EmptyState";
import { FiltersBar, SearchBox } from "@/components/Filters";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { errorText } from "@/features/users/labels";
import { pick, upTo } from "@/lib/url-guards";
import { useDebounced } from "@/lib/useDebounced";
import { useNarrow } from "@/lib/useNarrow";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;
/** The API's `q` ceiling (and the input's `maxLength`). */
const Q_MAX = 100;
const HEADERS = ["#", "Скин", "Источник", "Цена", "Обмен", "Покупатель", "Статус", "Время"];

export function TradesPage() {
  const narrow = useNarrow();
  const url = useUrlParams();
  const view: TradeView = pick(TRADE_VIEWS, url.get("view")) ?? "all";
  const urlQ = upTo(url.get("q"), Q_MAX);

  // The box starts from `?q=` and writes back once typing settles.
  const [text, setText] = useState(urlQ);
  const typed = useDebounced(text.trim(), DEBOUNCE_MS);
  const { set } = url;
  useEffect(() => {
    if (typed !== urlQ) set("q", typed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a settled edit writes the URL; an outside change of `q` must not be overwritten by a stale box
  }, [typed]);

  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (number: string) => {
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(number)) next.add(number);
      return next;
    });
  };

  const list = useInfiniteQuery<
    AdminTradesPage,
    Error,
    InfiniteData<AdminTradesPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...TRADES_KEY, "list", view, urlQ],
    queryFn: ({ pageParam }) => {
      const params: ListTradesParams = {
        view,
        ...(urlQ !== "" && { q: urlQ }),
        ...(pageParam !== null && { cursor: pageParam }),
      };
      return listTrades(params);
    },
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = list.data?.pages.flatMap((p) => p.items) ?? [];
  // The counts ride on every page; keep the last ones so the badges do not blink on a tab switch.
  const lastCounts = useRef<AdminTradeCounts | null>(null);
  const fresh = list.data?.pages[0]?.counts;
  if (fresh !== undefined) lastCounts.current = fresh;
  const counts = fresh ?? lastCounts.current;

  return (
    <section className="space-y-4">
      <PageHeader title="Обмены" />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Tabs<TradeView>
          label="Обмены"
          value={view}
          onChange={(v) => {
            url.set("view", v === "all" ? "" : v);
          }}
          items={TRADE_VIEWS.map((v) => ({
            key: v,
            label: TRADE_VIEW_LABELS[v],
            ...(counts !== null && { count: counts[v] }),
            alert: v === "attention",
          }))}
        />
        <FiltersBar>
          <SearchBox
            label="Номер, название или id обмена Steam"
            value={text}
            maxLength={Q_MAX}
            onChange={setText}
          />
        </FiltersBar>
      </div>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && <EmptyState tone="danger">{errorText(list.error)}</EmptyState>}
      {list.isSuccess && rows.length === 0 && <EmptyState>Здесь пусто.</EmptyState>}
      {rows.length > 0 && narrow && (
        <ul aria-label="Обмены" className="space-y-2">
          {rows.map((r) => (
            <li
              key={r.number}
              className={`border-border bg-surface rounded-lg border p-3 ${
                r.attention_reason !== null ? "border-l-danger border-l-[3px]" : ""
              }`}
            >
              <TradeCard row={r} />
            </li>
          ))}
        </ul>
      )}
      {rows.length > 0 && !narrow && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="trades-table">
            <thead className="text-fg-muted text-xs">
              <tr className="border-border border-b">
                {HEADERS.map((h, i) => (
                  <th
                    key={h}
                    className={`whitespace-nowrap py-2 pr-3 font-normal ${i === 0 ? "pl-3" : ""}`}
                  >
                    {h}
                  </th>
                ))}
                <th className="py-2 font-normal">
                  <span className="sr-only">Подробнее</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <TradeLine
                  key={r.number}
                  row={r}
                  open={open.has(r.number)}
                  onToggle={() => {
                    toggle(r.number);
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.hasNextPage && (
        <Button
          variant="secondary"
          size="sm"
          disabled={list.isFetchingNextPage}
          onClick={() => {
            void list.fetchNextPage();
          }}
        >
          Показать ещё
        </Button>
      )}
    </section>
  );
}
