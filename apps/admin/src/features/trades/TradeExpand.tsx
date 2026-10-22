/**
 * A trade's details under its row: the timeline with exact times (seconds: what an operator
 * matches against a market's or Steam's log), the source's own record in words, the Steam
 * offer, read from the order page's data (`GET /admin/orders/{number}`, fetched on expand).
 */
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";

import { type AdminTradeRow } from "./api";
import { SOURCE_LABELS } from "./labels";
import { type AdminOrderDetail, getOrder } from "../orders/api";
import { detailKey } from "../orders/keys";

import { Reason, Status } from "@/components/Status";
import { TradeLinkValue } from "@/components/SteamLinks";
import { LINK, TextLink } from "@/components/TextLink";
import { errorText } from "@/features/users/labels";
import { reasonText } from "@/lib/dictionary";
import { formatDateTimeSeconds } from "@/lib/format";

interface Step {
  label: string;
  at: string;
}

/** What happened, oldest first; steps not reached are left out. */
export function timeline(detail: AdminOrderDetail): Step[] {
  const o = detail.order;
  const refund = o.failure_reason === null ? "" : ` · ${reasonText("failure", o.failure_reason)}`;
  const steps: [string, string | null][] = [
    ["Создан", o.created_at],
    ["Оплачен", o.paid_at],
    ["Покупка начата", o.claimed_at],
    ["Обмен отправлен", o.trade_sent_at],
    ["Принят", detail.trade?.accepted_at ?? null],
    [o.protected_estimated ? "Защита Steam до (≈ +7 дней)" : "Защита Steam до", o.protected_until],
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

function SourceStatus({ status, waxpeer }: { status: string | null; waxpeer: boolean }) {
  if (status === null) return <>—</>;
  return <Status of={waxpeer ? "waxpeer" : "market"} code={status} />;
}

function MarketReason({ code }: { code: string | null }) {
  return code === null ? <>—</> : <Reason of="market" code={code} />;
}

/** The source's own record in words: its status, its purchase number and why it failed. */
function sourceFields(detail: AdminOrderDetail): [string, ReactNode][] {
  const { trade, skinslink, lisskins } = detail;
  if (skinslink !== null) {
    return [
      ["Статус", <SourceStatus key="s" status={skinslink.status} waxpeer={false} />],
      ["Покупка", skinslink.purchase_id === null ? "—" : String(skinslink.purchase_id)],
      ["Причина", <MarketReason key="r" code={skinslink.fail_reason} />],
    ];
  }
  if (lisskins !== null) {
    return [
      ["Статус", <SourceStatus key="s" status={lisskins.status} waxpeer={false} />],
      ["Покупка", lisskins.purchase_id === null ? "—" : String(lisskins.purchase_id)],
      ["Причина", <MarketReason key="r" code={lisskins.return_reason ?? lisskins.error} />],
    ];
  }
  if (trade !== null) {
    return [
      [
        "Статус",
        <SourceStatus
          key="s"
          status={trade.status === null ? null : String(trade.status)}
          waxpeer
        />,
      ],
      ["Покупка", trade.waxpeer_id === null ? "—" : String(trade.waxpeer_id)],
      ["Причина", <MarketReason key="r" code={trade.reason} />],
    ];
  }
  return [];
}

/** The Steam offer of the trade (it left the row: it is «—» on most of them). */
function SteamOffer({ row }: { row: AdminTradeRow }) {
  if (row.offer_url === null || row.steam_offer_id === null) return null;
  return (
    <p className="mt-2">
      <span className="text-fg-muted">Обмен в Steam: </span>
      <a href={row.offer_url} target="_blank" rel="noreferrer" className={LINK}>
        {row.steam_offer_id}
      </a>
    </p>
  );
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
                <time dateTime={s.at} className="text-fg-muted w-40 shrink-0 tabular-nums">
                  {formatDateTimeSeconds(s.at)}
                </time>
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
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <SteamOffer row={row} />
            {row.trade_link !== null && (
              <p className="text-fg-muted mt-2 text-xs">
                Трейд-ссылка: <TradeLinkValue link={row.trade_link} />
              </p>
            )}
          </div>
        </div>
      )}
      <TextLink to={`/orders/${row.number}`} className="inline-block">
        Открыть заказ →
      </TextLink>
    </div>
  );
}
