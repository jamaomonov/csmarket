/** A trade's details under its row: the timeline and the source's own record, read from the
 * order page's data (`GET /admin/orders/{number}`, fetched on expand). */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { type AdminTradeRow } from "./api";
import { SOURCE_LABELS } from "./labels";
import { type AdminOrderDetail, getOrder } from "../orders/api";
import { detailKey } from "../orders/keys";
import { FAILURE_LABELS, waxpeerStatusLabel } from "../orders/labels";

import { errorText } from "@/features/users/labels";
import { formatDateTime } from "@/lib/format";

interface Step {
  label: string;
  at: string;
}

/** What happened, oldest first; steps not reached are left out. */
export function timeline(detail: AdminOrderDetail): Step[] {
  const o = detail.order;
  const refund = o.failure_reason === null ? "" : ` · ${FAILURE_LABELS[o.failure_reason]}`;
  const steps: [string, string | null][] = [
    ["Создан", o.created_at],
    ["Оплачен", o.paid_at],
    ["Покупка начата", o.claimed_at],
    ["Обмен отправлен", o.trade_sent_at],
    ["Принят", detail.trade?.accepted_at ?? null],
    ["Защита Steam до", o.protected_until],
    ["Получен", o.delivered_at],
    ["Отменён", o.cancelled_at],
    [`Не получилось${o.refunded_at === null ? refund : ""}`, o.failed_at],
    [`Возврат на баланс${refund}`, o.refunded_at],
  ];
  return steps
    .filter((s): s is [string, string] => s[1] !== null)
    .map(([label, at]) => ({ label, at }))
    .sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
}

/** The source's own record: its status word, ids and why it failed. */
function sourceFields(detail: AdminOrderDetail): [string, string][] {
  const { trade, skinslink, lisskins } = detail;
  if (skinslink !== null) {
    return [
      ["Статус", skinslink.status ?? "—"],
      ["Покупка", skinslink.purchase_id === null ? "—" : String(skinslink.purchase_id)],
      ["Причина", skinslink.fail_reason ?? "—"],
    ];
  }
  if (lisskins !== null) {
    return [
      ["Статус", lisskins.status ?? "—"],
      ["Покупка", lisskins.purchase_id === null ? "—" : String(lisskins.purchase_id)],
      ["Причина", lisskins.return_reason ?? lisskins.error ?? "—"],
    ];
  }
  if (trade !== null) {
    return [
      ["Статус", waxpeerStatusLabel(trade.status)],
      ["Waxpeer id", trade.waxpeer_id === null ? "—" : String(trade.waxpeer_id)],
      ["Причина", trade.reason ?? "—"],
    ];
  }
  return [];
}

export function TradeExpand({ row }: { row: AdminTradeRow }) {
  const query = useQuery({
    queryKey: detailKey(row.number),
    queryFn: () => getOrder(row.number),
  });
  const detail = query.data;
  return (
    <div className="space-y-3 text-sm" data-testid="trade-details">
      {query.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {query.isError && (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      )}
      {detail && (
        <div className="grid gap-6 md:grid-cols-2">
          <ol className="space-y-1" aria-label="Ход обмена">
            {timeline(detail).map((s) => (
              <li key={s.label} className="flex gap-3">
                <span className="text-fg-muted w-32 shrink-0 tabular-nums">
                  {formatDateTime(s.at)}
                </span>
                <span>{s.label}</span>
              </li>
            ))}
          </ol>
          <div>
            <p className="mb-1 font-medium">{SOURCE_LABELS[row.source]}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              {sourceFields(detail).map(([name, value]) => (
                <div key={name} className="contents">
                  <dt className="text-fg-muted">{name}</dt>
                  <dd className="font-mono">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}
      <Link to={`/orders/${row.number}`} className="text-accent inline-block hover:underline">
        Открыть заказ →
      </Link>
    </div>
  );
}
