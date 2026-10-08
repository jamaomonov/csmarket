/** «Заявки на выплату»: status tabs with counts («К выплате» first), newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listPayouts, PAYOUT_STATUSES, type PayoutRow, type PayoutsPage as Page } from "./api";
import { PAYOUTS_KEY } from "./keys";
import { cardLabel, PAYOUT_LABELS } from "./labels";

import { errorText } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

function Row({ row }: { row: PayoutRow }) {
  return (
    <tr className="border-border border-t">
      <td className="py-2 pr-3">
        <Link to={`/payouts/${row.id}`} className="font-mono font-medium hover:underline">
          {row.sale_number}
        </Link>
      </td>
      <td className="py-2 pr-3">
        <Link to={`/users/${row.user.id}`} className="hover:underline">
          {row.user.display_name ?? "Без имени"}
        </Link>
      </td>
      <td className="py-2 pr-3">{cardLabel(row.card_type, row.card_masked)}</td>
      <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
        {formatSum(row.amount_uzs)}
      </td>
      <td className="text-fg-muted whitespace-nowrap py-2">
        {row.to_pay_at ? formatDateTime(row.to_pay_at) : "—"}
      </td>
    </tr>
  );
}

export function PayoutsPage() {
  const url = useUrlParams();
  const status = pick(PAYOUT_STATUSES, url.get("status")) ?? "to_pay";
  const query = useInfiniteQuery<
    Page,
    Error,
    InfiniteData<Page, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...PAYOUTS_KEY, status],
    queryFn: ({ pageParam }) => listPayouts(status, pageParam ?? undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const counts = query.data?.pages[0]?.counts;
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Заявки на выплату</h1>
      <nav aria-label="Статусы" className="flex flex-wrap gap-2">
        {PAYOUT_STATUSES.map((s) => (
          <Link
            key={s}
            to={`/payouts?status=${s}`}
            aria-current={s === status ? "page" : undefined}
            className={
              s === status
                ? "bg-accent text-accent-fg rounded-md px-3 py-1.5 text-sm"
                : "bg-surface-2 rounded-md px-3 py-1.5 text-sm"
            }
          >
            {PAYOUT_LABELS[s]} {counts?.[s] ?? 0}
          </Link>
        ))}
      </nav>
      {query.isError ? (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      ) : query.isPending ? (
        <p className="text-fg-muted">Загрузка…</p>
      ) : items.length === 0 ? (
        <p className="text-fg-muted">Заявок нет.</p>
      ) : (
        <table className="w-full text-sm" data-testid="payouts-table">
          <thead className="text-fg-muted text-left">
            <tr>
              <th className="py-2 pr-3 font-medium">Продажа</th>
              <th className="py-2 pr-3 font-medium">Пользователь</th>
              <th className="py-2 pr-3 font-medium">Карта</th>
              <th className="py-2 pr-3 text-right font-medium">Сумма</th>
              <th className="py-2 font-medium">К выплате с</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <Row key={row.id} row={row} />
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
