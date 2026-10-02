/** «Обмены»: orders with a Waxpeer trade — all, in flight, and those that need an operator. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { Link } from "react-router-dom";

import { type AdminTradeCounts, type AdminTradeRow, type AdminTradesPage, listTrades } from "./api";
import { TRADE_VIEWS, type TradeState, type TradeView } from "../orders/kinds";
import { TRADE_VIEW_LABELS } from "../orders/labels";
import { AttentionBadge, OrderStatusChip } from "../orders/StatusChip";

import { errorText } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

const STATE_LABELS: Record<TradeState, string> = {
  buying: "покупаем",
  offer_sent: "предложение отправлено",
  accepted: "принят, защита Steam",
  released: "выдан",
  failed: "сорвался",
};

/** The count the tab shows; `«Все»` has none. */
function countFor(view: TradeView, counts: AdminTradeCounts | null): number | null {
  if (counts === null) return null;
  if (view === "active") return counts.active;
  if (view === "attention") return counts.attention;
  return null;
}

function TradeRow({ row }: { row: AdminTradeRow }) {
  return (
    <tr
      className={`border-border border-t ${row.attention_reason !== null ? "bg-danger/10" : ""}`}
      {...(row.attention_reason !== null && { "data-attention": "true" })}
    >
      <td className="py-2 pr-3">
        <Link to={`/orders/${row.number}`} className="font-mono font-medium hover:underline">
          {row.number}
        </Link>
      </td>
      <td className="py-2 pr-3">{row.name}</td>
      <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
        {formatSum(row.price_uzs)}
      </td>
      <td className="py-2 pr-3">
        <div className="flex flex-wrap items-center gap-1">
          <OrderStatusChip status={row.status} />
          <AttentionBadge reason={row.attention_reason} />
        </div>
      </td>
      <td className="py-2 pr-3">{STATE_LABELS[row.trade.state]}</td>
      <td className="whitespace-nowrap py-2 pr-3">
        {row.trade.send_until === null ? "—" : formatDateTime(row.trade.send_until)}
      </td>
      <td className="py-2 pr-3">
        <Link to={`/users/${row.user.id}`} className="hover:underline">
          {row.user.display_name ?? "Без имени"}
        </Link>
      </td>
      <td className="text-fg-muted whitespace-nowrap py-2">{formatDateTime(row.created_at)}</td>
    </tr>
  );
}

export function TradesPage() {
  const url = useUrlParams();
  const view: TradeView = pick(TRADE_VIEWS, url.get("view")) ?? "all";

  const list = useInfiniteQuery<
    AdminTradesPage,
    Error,
    InfiniteData<AdminTradesPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: ["admin", "trades", "list", view],
    queryFn: ({ pageParam }) =>
      listTrades({ view, ...(pageParam !== null && { cursor: pageParam }) }),
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
    <section className="space-y-6">
      <h1 className="text-2xl font-bold">Обмены</h1>
      <div role="tablist" aria-label="Обмены" className="border-border flex gap-1 border-b">
        {TRADE_VIEWS.map((v) => {
          const n = countFor(v, counts);
          const selected = v === view;
          return (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => {
                url.set("view", v === "all" ? "" : v);
              }}
              className={`-mb-px border-b-2 px-3 py-2 text-sm ${
                selected
                  ? "border-accent text-fg font-medium"
                  : "text-fg-muted hover:text-fg border-transparent"
              }`}
            >
              {TRADE_VIEW_LABELS[v]}
              {n !== null && (
                <>
                  {" "}
                  <span className="tabular-nums">{n}</span>
                </>
              )}
            </button>
          );
        })}
      </div>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.isSuccess && rows.length === 0 && <p className="text-fg-muted">Здесь пусто.</p>}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="trades-table">
            <thead className="text-fg-muted">
              <tr>
                <th className="py-1 font-normal">Номер</th>
                <th className="py-1 font-normal">Скин</th>
                <th className="py-1 text-right font-normal">Цена</th>
                <th className="py-1 font-normal">Заказ</th>
                <th className="py-1 font-normal">Обмен</th>
                <th className="py-1 font-normal">Отправить до</th>
                <th className="py-1 font-normal">Пользователь</th>
                <th className="py-1 font-normal">Создан</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <TradeRow key={r.number} row={r} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.hasNextPage && (
        <Button
          variant="secondary"
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
