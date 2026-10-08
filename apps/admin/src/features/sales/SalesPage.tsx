/** «Продажи»: find a sale by number, filter by status, newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { type AdminSalesPage, listSales, SALE_STATUSES } from "./api";
import { SALES_LIST_KEY } from "./keys";
import { ATTENTION_LABELS, SALE_LABELS } from "./labels";

import { errorText } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";
import { pick, upTo } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

export function SalesPage() {
  const url = useUrlParams();
  const status = pick(SALE_STATUSES, url.get("status"));
  const q = upTo(url.get("q"), 8);
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
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Продажи</h1>
      <div className="flex gap-2">
        <input
          aria-label="Номер продажи"
          placeholder="S…"
          maxLength={8}
          defaultValue={q}
          onChange={(e) => {
            url.set("q", e.target.value.trim());
          }}
          className="border-border bg-bg rounded-md border px-3 py-1.5"
        />
        <select
          aria-label="Статус"
          value={status ?? ""}
          onChange={(e) => {
            url.set("status", e.target.value);
          }}
          className="border-border bg-bg rounded-md border px-3 py-1.5"
        >
          <option value="">Все</option>
          {SALE_STATUSES.map((s) => (
            <option key={s} value={s}>
              {SALE_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
      {query.isError ? (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-fg-muted text-left">
            <tr>
              <th className="py-2 pr-3 font-medium">Номер</th>
              <th className="py-2 pr-3 font-medium">Статус</th>
              <th className="py-2 pr-3 font-medium">Пользователь</th>
              <th className="py-2 pr-3 text-right font-medium">Skinslink, $</th>
              <th className="py-2 pr-3 text-right font-medium">Выплата</th>
              <th className="py-2 pr-3 text-right font-medium">Маржа, $</th>
              <th className="py-2 font-medium">Создана</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.number} className="border-border border-t">
                <td className="py-2 pr-3">
                  <Link to={`/sales/${s.number}`} className="font-mono font-medium hover:underline">
                    {s.number}
                  </Link>
                </td>
                <td className="py-2 pr-3">
                  {SALE_LABELS[s.status]}
                  {s.attention_reason ? (
                    <div className="text-danger text-xs">
                      {ATTENTION_LABELS[s.attention_reason] ?? s.attention_reason}
                    </div>
                  ) : null}
                </td>
                <td className="py-2 pr-3">
                  <Link to={`/users/${s.user.id}`} className="hover:underline">
                    {s.user.display_name ?? "Без имени"}
                  </Link>
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">{s.quoted_usd}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{formatSum(s.payout_uzs)}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{s.margin_usd}</td>
                <td className="text-fg-muted py-2">{formatDateTime(s.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {query.hasNextPage ? (
        <Button
          variant="secondary"
          className="self-start"
          onClick={() => void query.fetchNextPage()}
        >
          Показать ещё
        </Button>
      ) : null}
    </div>
  );
}
