/** «Заказ»: fields and money, payments, the Waxpeer trade and the operator's actions. */
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { type AdminOrderDetail, getOrder } from "./api";
import { detailKey } from "./keys";
import { FAILURE_LABELS } from "./labels";
import { OrderActions } from "./OrderActions";
import { SkinslinkBlock } from "./SkinslinkBlock";
import { AttentionBadge, OrderStatusChip } from "./StatusChip";
import { TradeBlock } from "./TradeBlock";

import { StatusChip as PaymentStatusChip } from "@/features/payments/StatusChip";
import { errorText, providerLabel } from "@/features/users/labels";
import { ApiError } from "@/lib/api";
import { formatDateTime, formatSum } from "@/lib/format";

const SOURCE_LABELS: Record<AdminOrderDetail["order"]["source"], string> = {
  waxpeer: "Waxpeer",
  skinslink: "Skinslink",
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="text-fg-muted w-40 shrink-0">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

const usd = (value: string): string => `$${value}`;

function OrderFields({ detail }: { detail: AdminOrderDetail }) {
  const { order, user } = detail;
  return (
    <section aria-label="Заказ" className="space-y-2">
      <dl className="space-y-1 text-sm">
        <Field label="Скин">
          {order.market_hash_name}
          {order.phase !== null && <span className="text-fg-muted"> · {order.phase}</span>}
        </Field>
        <Field label="Статус">
          <OrderStatusChip status={order.status} />
        </Field>
        <Field label="Пользователь">
          <Link to={`/users/${user.id}`} className="hover:underline">
            {user.display_name ?? "Без имени"}
          </Link>
        </Field>
        <Field label="Источник">
          {SOURCE_LABELS[order.source]}
          {order.offer_id !== null && ` · ${order.offer_id}`}
        </Field>
        <Field label="Цена">{formatSum(order.price_uzs)}</Field>
        <Field label="Цена, USD">{usd(order.price_usd)}</Field>
        <Field label="Себестоимость, USD">{usd(order.cost_usd)}</Field>
        <Field label="Маржа, USD">{usd(order.margin_usd)}</Field>
        <Field label="Курс">{order.fx_rate}</Field>
        <Field label="Оплата">{providerLabel(order.paid_with)}</Field>
        <Field label="Трейд-ссылка">{order.trade_link_masked ?? "не указана"}</Field>
        <Field label="Создан">{when(order.created_at)}</Field>
        <Field label="Действует до">{when(order.expires_at)}</Field>
        <Field label="Оплачен">{when(order.paid_at)}</Field>
        <Field label="Получен">{when(order.delivered_at)}</Field>
        {order.cancelled_at !== null && <Field label="Отменён">{when(order.cancelled_at)}</Field>}
        {order.failed_at !== null && (
          <Field label="Не получилось">
            {when(order.failed_at)}
            {order.failure_reason !== null && ` · ${FAILURE_LABELS[order.failure_reason]}`}
          </Field>
        )}
        {order.refunded_at !== null && (
          <Field label="Возврат">{when(order.refunded_at)} · на баланс</Field>
        )}
      </dl>
    </section>
  );
}

function Payments({ payments }: { payments: AdminOrderDetail["payments"] }) {
  return (
    <section aria-label="Платежи" className="space-y-2">
      <h2 className="text-lg font-semibold">Платежи</h2>
      {payments.length === 0 && <p className="text-fg-muted text-sm">Оплаты не было.</p>}
      <ul className="divide-border divide-y text-sm">
        {payments.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
            <Link to={`/payments/${p.id}`} className="hover:underline">
              {providerLabel(p.provider)} · {formatSum(p.amount_uzs)}
            </Link>
            <PaymentStatusChip status={p.status} />
            <span className="text-fg-muted">{formatDateTime(p.created_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function OrderDetail() {
  const { number = "" } = useParams();
  const query = useQuery({
    queryKey: detailKey(number),
    queryFn: () => getOrder(number),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
  const notFound = query.error instanceof ApiError && query.error.status === 404;
  const detail = query.data;
  const open =
    detail?.trade?.attention_reason != null && detail.trade.resolved_at === null
      ? detail.trade.attention_reason
      : null;

  return (
    <section className="space-y-6">
      <Link to="/orders" className="text-fg-muted text-sm hover:underline">
        ← Все заказы
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{detail ? `Заказ ${detail.order.number}` : "Заказ"}</h1>
        <AttentionBadge reason={open} />
      </div>
      {query.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {notFound && <p className="text-fg-muted">Заказ не найден.</p>}
      {query.isError && !notFound && (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      )}
      {detail && (
        <div className="space-y-8" data-testid="order-detail">
          <OrderFields detail={detail} />
          <Payments payments={detail.payments} />
          {detail.skinslink !== null ? (
            <SkinslinkBlock purchase={detail.skinslink} />
          ) : (
            <TradeBlock trade={detail.trade} />
          )}
          <OrderActions
            key={detail.order.number}
            detail={detail}
            onStale={() => {
              void query.refetch();
            }}
          />
        </div>
      )}
    </section>
  );
}
