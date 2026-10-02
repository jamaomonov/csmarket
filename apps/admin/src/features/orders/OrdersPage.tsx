/** «Заказы»: find an order by number or skin name, filter by status, newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type AdminOrderRow, type AdminOrdersPage, listOrders, type ListOrdersParams } from "./api";
import { ORDERS_LIST_KEY } from "./keys";
import { ORDER_STATUSES } from "./kinds";
import { STATUS_LABELS } from "./labels";
import { AttentionBadge, OrderStatusChip } from "./StatusChip";

import { errorText, providerLabel } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";
import { pick, upTo } from "@/lib/url-guards";
import { useDebounced } from "@/lib/useDebounced";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;
/** The API's `q` ceiling (and the input's `maxLength`). */
const Q_MAX = 100;

function OrderRow({ order }: { order: AdminOrderRow }) {
  return (
    <tr className="border-border border-t">
      <td className="py-2 pr-3">
        <Link to={`/orders/${order.number}`} className="font-mono font-medium hover:underline">
          {order.number}
        </Link>
      </td>
      <td className="py-2 pr-3">
        {order.name}
        {order.phase !== null && <div className="text-fg-muted text-xs">{order.phase}</div>}
      </td>
      <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
        {formatSum(order.price_uzs)}
      </td>
      <td className="py-2 pr-3">{providerLabel(order.paid_with)}</td>
      <td className="py-2 pr-3">
        <div className="flex flex-wrap items-center gap-1">
          <OrderStatusChip status={order.status} />
          <AttentionBadge reason={order.attention_reason} />
        </div>
      </td>
      <td className="py-2 pr-3">
        <Link to={`/users/${order.user.id}`} className="hover:underline">
          {order.user.display_name ?? "Без имени"}
        </Link>
      </td>
      <td className="text-fg-muted whitespace-nowrap py-2">{formatDateTime(order.created_at)}</td>
    </tr>
  );
}

export function OrdersPage() {
  const url = useUrlParams();
  const urlQ = upTo(url.get("q"), Q_MAX);
  const status = pick(ORDER_STATUSES, url.get("status"));

  // The box starts from `?q=` and writes back once typing settles.
  const [text, setText] = useState(urlQ);
  const typed = useDebounced(text.trim(), DEBOUNCE_MS);
  const { set } = url;
  useEffect(() => {
    if (typed !== urlQ) set("q", typed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a settled edit writes the URL; an outside change of `q` must not be overwritten by a stale box
  }, [typed]);

  const list = useInfiniteQuery<
    AdminOrdersPage,
    Error,
    InfiniteData<AdminOrdersPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...ORDERS_LIST_KEY, urlQ, status],
    queryFn: ({ pageParam }) => {
      const params: ListOrdersParams = {
        ...(urlQ !== "" && { q: urlQ }),
        ...(status && { status }),
        ...(pageParam !== null && { cursor: pageParam }),
      };
      return listOrders(params);
    },
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const orders = list.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-bold">Заказы</h1>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex max-w-xs flex-col gap-1 text-sm">
          Номер заказа или название
          <input
            type="search"
            value={text}
            maxLength={Q_MAX}
            onChange={(e) => {
              setText(e.target.value);
            }}
            className="border-border bg-bg h-10 rounded-md border px-3 text-base"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Статус
          <select
            value={status ?? ""}
            onChange={(e) => {
              url.set("status", e.target.value);
            }}
            className="border-border bg-bg h-10 rounded-md border px-3 text-base"
          >
            <option value="">Все</option>
            {ORDER_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.isSuccess && orders.length === 0 && <p className="text-fg-muted">Ничего не нашли.</p>}
      {orders.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="orders-table">
            <thead className="text-fg-muted">
              <tr>
                <th className="py-1 font-normal">Номер</th>
                <th className="py-1 font-normal">Скин</th>
                <th className="py-1 text-right font-normal">Цена</th>
                <th className="py-1 font-normal">Оплата</th>
                <th className="py-1 font-normal">Статус</th>
                <th className="py-1 font-normal">Пользователь</th>
                <th className="py-1 font-normal">Создан</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <OrderRow key={o.number} order={o} />
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
