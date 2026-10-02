/** «Платёж»: one payment, its top-up and the kassa's own transactions. Read-only. */
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import {
  type AdminPaymentDetail,
  getPayment,
  type KassaTxn,
  type PaymentOrder,
  type PaymentTopup,
} from "./api";
import {
  EXTRA_LABELS,
  formatKassaAmount,
  kassaStatusLabel,
  PURPOSE_LABELS,
  safeExtraValue,
} from "./labels";
import { StatusChip } from "./StatusChip";

import { OrderStatusChip } from "@/features/orders/StatusChip";
import { errorText, providerLabel, topupStatusLabel } from "@/features/users/labels";
import { ApiError } from "@/lib/api";
import { formatDateTime, formatSum } from "@/lib/format";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="text-fg-muted w-40 shrink-0">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

function TopupBlock({ topup }: { topup: PaymentTopup }) {
  return (
    <section aria-label="Пополнение" className="space-y-2">
      <h2 className="text-lg font-semibold">Пополнение</h2>
      <dl className="space-y-1 text-sm">
        <Field label="Номер">
          <span className="font-mono">{topup.number}</span>
        </Field>
        <Field label="Сумма">{formatSum(topup.amount_uzs)}</Field>
        <Field label="Статус">{topupStatusLabel(topup.status)}</Field>
        <Field label="Действует до">{when(topup.expires_at)}</Field>
        <Field label="Зачислено">{when(topup.succeeded_at)}</Field>
      </dl>
    </section>
  );
}

function OrderBlock({ order }: { order: PaymentOrder }) {
  return (
    <section aria-label="Заказ" className="space-y-2">
      <h2 className="text-lg font-semibold">Заказ</h2>
      <dl className="space-y-1 text-sm">
        <Field label="Номер">
          <Link to={`/orders/${order.number}`} className="font-mono hover:underline">
            {order.number}
          </Link>
        </Field>
        <Field label="Цена">{formatSum(order.price_uzs)}</Field>
        <Field label="Статус">
          <OrderStatusChip status={order.status} />
        </Field>
      </dl>
    </section>
  );
}

/** Only the allow-listed `extra` keys; anything else the API might add stays unseen. */
function ExtraList({ extra }: { extra: Record<string, string> }) {
  const lines = EXTRA_LABELS.flatMap(([key, label]) => {
    const value = extra[key];
    return value === undefined ? [] : [{ key, label, value: safeExtraValue(key, value) }];
  });
  return (
    <ul className="space-y-0.5">
      {lines.map((l) => (
        <li key={l.key}>
          <span className="text-fg-muted">{l.label}:</span> {l.value}
        </li>
      ))}
    </ul>
  );
}

function KassaTimes({ times }: { times: KassaTxn["times"] }) {
  return (
    <ul className="space-y-0.5">
      <li>создана: {when(times.created)}</li>
      {times.performed !== null && <li>проведена: {formatDateTime(times.performed)}</li>}
      {times.cancelled !== null && <li>отменена: {formatDateTime(times.cancelled)}</li>}
    </ul>
  );
}

function KassaTable({ kassa }: { kassa: KassaTxn[] }) {
  return (
    <section aria-label="Транзакции кассы" className="space-y-2">
      <h2 className="text-lg font-semibold">Транзакции кассы</h2>
      {kassa.length === 0 ? (
        <p className="text-fg-muted text-sm">Касса ещё не обращалась.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="kassa-table">
            <thead className="text-fg-muted">
              <tr>
                <th className="py-1 font-normal">Касса</th>
                <th className="py-1 font-normal">Внешний id</th>
                <th className="py-1 font-normal">Статус</th>
                <th className="py-1 text-right font-normal">Сумма</th>
                <th className="py-1 pl-3 font-normal">Время</th>
                <th className="py-1 pl-3 font-normal">Данные</th>
              </tr>
            </thead>
            <tbody>
              {kassa.map((k) => (
                <tr
                  key={`${k.provider}:${k.external_id}`}
                  className="border-border border-t align-top"
                >
                  <td className="py-2 pr-3">{providerLabel(k.provider)}</td>
                  <td className="break-all py-2 pr-3 font-mono">{k.external_id}</td>
                  <td className="py-2 pr-3" title={k.status}>
                    {kassaStatusLabel(k.status)}
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
                    {formatKassaAmount(k)}
                  </td>
                  <td className="text-fg-muted whitespace-nowrap py-2 pl-3 pr-3">
                    <KassaTimes times={k.times} />
                  </td>
                  <td className="py-2 pl-3">
                    <ExtraList extra={k.extra} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Body({ detail }: { detail: AdminPaymentDetail }) {
  const { payment, topup, order, kassa } = detail;
  return (
    <div className="space-y-8" data-testid="payment-detail">
      <section aria-label="Платёж" className="space-y-2">
        <dl className="space-y-1 text-sm">
          <Field label="Назначение">{PURPOSE_LABELS[payment.purpose]}</Field>
          <Field label="Сумма">{formatSum(payment.amount_uzs)}</Field>
          <Field label="Касса">{providerLabel(payment.provider)}</Field>
          <Field label="Статус">
            <StatusChip status={payment.status} />
          </Field>
          <Field label="Пользователь">
            <Link to={`/users/${payment.user.id}`} className="hover:underline">
              {payment.user.display_name ?? "Без имени"}
            </Link>
          </Field>
          <Field label="Создан">{formatDateTime(payment.created_at)}</Field>
          <Field label="Оплачен">{when(payment.succeeded_at)}</Field>
          <Field label="Номер в кассе">
            {payment.provider_ref === null ? (
              "—"
            ) : (
              <span className="font-mono">{payment.provider_ref}</span>
            )}
          </Field>
        </dl>
      </section>
      {topup !== null && <TopupBlock topup={topup} />}
      {order !== null && <OrderBlock order={order} />}
      <KassaTable kassa={kassa} />
    </div>
  );
}

export function PaymentDetail() {
  const { id = "" } = useParams();
  const query = useQuery({
    queryKey: ["admin", "payments", "detail", id],
    queryFn: () => getPayment(id),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
  const notFound = query.error instanceof ApiError && query.error.status === 404;

  return (
    <section className="space-y-6">
      <Link to="/payments" className="text-fg-muted text-sm hover:underline">
        ← Все платежи
      </Link>
      <h1 className="text-2xl font-bold">
        {query.data ? `Платёж ${query.data.payment.number}` : "Платёж"}
      </h1>
      {query.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {notFound && <p className="text-fg-muted">Платёж не найден.</p>}
      {query.isError && !notFound && (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      )}
      {query.data && <Body detail={query.data} />}
    </section>
  );
}
