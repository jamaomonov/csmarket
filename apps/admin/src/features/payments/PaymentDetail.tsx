/** «Платёж»: one payment, its top-up and the kassa's own transactions. Read-only. */
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

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

import { PageHeader } from "@/components/PageHeader";
import { DetailGrid, More, Row, Section } from "@/components/Section";
import { Status } from "@/components/Status";
import { TextLink } from "@/components/TextLink";
import { UserCell } from "@/components/UserCell";
import { errorText, providerLabel } from "@/features/users/labels";
import { ApiError } from "@/lib/api";
import { formatDateTime, formatSum } from "@/lib/format";

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

function TopupBlock({ topup }: { topup: PaymentTopup }) {
  return (
    <Section title="Пополнение">
      <dl>
        <Row label="Номер">
          <span className="font-mono">{topup.number}</span>
        </Row>
        <Row label="Сумма">{formatSum(topup.amount_uzs)}</Row>
        <Row label="Статус">
          <Status of="topup" code={topup.status} />
        </Row>
        <Row label="Действует до">{when(topup.expires_at)}</Row>
        <Row label="Зачислено">{when(topup.succeeded_at)}</Row>
      </dl>
    </Section>
  );
}

function OrderBlock({ order }: { order: PaymentOrder }) {
  return (
    <Section title="Заказ">
      <dl>
        <Row label="Номер">
          <TextLink to={`/orders/${order.number}`} number>
            {order.number}
          </TextLink>
        </Row>
        <Row label="Цена">{formatSum(order.price_uzs)}</Row>
        <Row label="Статус">
          <Status of="order" code={order.status} testId="order-status" />
        </Row>
      </dl>
    </Section>
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
    <Section title="Транзакции кассы">
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
    </Section>
  );
}

function PaymentBlock({ payment }: { payment: AdminPaymentDetail["payment"] }) {
  return (
    <Section title="Платёж">
      <dl>
        <Row label="Назначение">{PURPOSE_LABELS[payment.purpose]}</Row>
        <Row label="Сумма">{formatSum(payment.amount_uzs)}</Row>
        {payment.fee_uzs !== "0" && <Row label="Комиссия кассы">{formatSum(payment.fee_uzs)}</Row>}
        <Row label="Касса">{providerLabel(payment.provider)}</Row>
        <Row label="Статус">
          <Status of="payment" code={payment.status} testId="payment-status" />
        </Row>
        <Row label="Пользователь">
          <UserCell
            id={payment.user.id}
            name={payment.user.display_name}
            avatarUrl={payment.user.avatar_url}
          />
        </Row>
        <Row label="Создан">{formatDateTime(payment.created_at)}</Row>
        <Row label="Оплачен">{when(payment.succeeded_at)}</Row>
      </dl>
      <More>
        <Row label="Номер в кассе">
          {payment.provider_ref === null ? (
            "—"
          ) : (
            <span className="break-all">{payment.provider_ref}</span>
          )}
        </Row>
      </More>
    </Section>
  );
}

function Body({ detail }: { detail: AdminPaymentDetail }) {
  const { payment, topup, order, kassa } = detail;
  const what =
    order !== null ? (
      <OrderBlock order={order} />
    ) : topup !== null ? (
      <TopupBlock topup={topup} />
    ) : undefined;
  return (
    <div className="space-y-4" data-testid="payment-detail">
      <DetailGrid main={<PaymentBlock payment={payment} />} side={what} />
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
    <section className="space-y-4">
      <PageHeader
        back={{ to: "/payments", label: "Все платежи" }}
        title={query.data ? `Платёж ${query.data.payment.number}` : "Платёж"}
        badges={
          query.data && (
            <Status of="payment" code={query.data.payment.status} testId="payment-status" />
          )
        }
      />
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
