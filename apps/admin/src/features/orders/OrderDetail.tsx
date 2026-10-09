/** «Заказ»: actions and an open attention first, then the order, the market, money and time. */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { type AdminOrderDetail, getOrder } from "./api";
import { detailKey } from "./keys";
import { type AttentionReason } from "./kinds";
import { ATTENTION_LABELS, FAILURE_LABELS } from "./labels";
import { LisskinsBlock } from "./LisskinsBlock";
import { OrderActions } from "./OrderActions";
import { SkinslinkBlock } from "./SkinslinkBlock";
import { AttentionBadge, OrderStatusChip } from "./StatusChip";
import { TradeBlock } from "./TradeBlock";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Banner, DetailGrid, Row, Section } from "@/components/Section";
import { StatusChip as PaymentStatusChip } from "@/features/payments/StatusChip";
import { errorText, providerLabel } from "@/features/users/labels";
import { ApiError } from "@/lib/api";
import { formatDateTime, formatSum } from "@/lib/format";

const SOURCE_LABELS: Record<AdminOrderDetail["order"]["source"], string> = {
  waxpeer: "Waxpeer",
  skinslink: "Skinslink",
  lisskins: "LIS-SKINS",
};

interface BoughtProps {
  detail: AdminOrderDetail;
}

/** The market's side of the order: a purchase block, or the Waxpeer trade. */
function Bought({ detail }: BoughtProps) {
  if (detail.skinslink !== null) return <SkinslinkBlock purchase={detail.skinslink} />;
  if (detail.lisskins !== null) return <LisskinsBlock purchase={detail.lisskins} />;
  return <TradeBlock trade={detail.trade} />;
}

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

/** The open attention of whichever market the order was bought at. */
function openAttention(detail: AdminOrderDetail): AttentionReason | null {
  const watched = detail.trade ?? detail.skinslink ?? detail.lisskins;
  if (watched?.resolved_at !== null) return null;
  return watched.attention_reason;
}

function OrderFields({ detail }: { detail: AdminOrderDetail }) {
  const { order, user } = detail;
  return (
    <Section title="Заказ">
      <dl>
        <Row label="Скин">
          {order.market_hash_name}
          {order.phase !== null && <span className="text-fg-muted"> · {order.phase}</span>}
        </Row>
        <Row label="Пользователь">
          <Link to={`/users/${user.id}`} className="hover:underline">
            {user.display_name ?? "Без имени"}
          </Link>
        </Row>
        <Row label="Источник">
          {SOURCE_LABELS[order.source]}
          {order.offer_id !== null && <span className="text-fg-muted"> · {order.offer_id}</span>}
        </Row>
        <Row label="Трейд-ссылка">
          <span className="break-all">{order.trade_link_masked ?? "не указана"}</span>
        </Row>
      </dl>
    </Section>
  );
}

function Timeline({ detail }: { detail: AdminOrderDetail }) {
  const { order } = detail;
  return (
    <Section title="Ход заказа">
      <dl>
        <Row label="Создан">{when(order.created_at)}</Row>
        <Row label="Действует до">{when(order.expires_at)}</Row>
        <Row label="Оплачен">{when(order.paid_at)}</Row>
        <Row label="Получен">{when(order.delivered_at)}</Row>
        {order.cancelled_at !== null && <Row label="Отменён">{when(order.cancelled_at)}</Row>}
        {order.failed_at !== null && (
          <Row label="Не получилось">
            {when(order.failed_at)}
            {order.failure_reason !== null && ` · ${FAILURE_LABELS[order.failure_reason]}`}
          </Row>
        )}
        {order.refunded_at !== null && (
          <Row label="Возврат">{when(order.refunded_at)} · на баланс</Row>
        )}
      </dl>
    </Section>
  );
}

function MoneyFields({ detail }: { detail: AdminOrderDetail }) {
  const { order } = detail;
  return (
    <Section title="Деньги">
      <dl>
        <Row label="Цена">
          <Money uzs={order.price_uzs} />
        </Row>
        <Row label="Цена, USD">
          <Money usd={order.price_usd} />
        </Row>
        <Row label="Себестоимость">
          <Money usd={order.cost_usd} />
        </Row>
        <Row label="Маржа">
          <Money usd={order.margin_usd} />
        </Row>
        <Row label="Курс">{order.fx_rate}</Row>
        <Row label="Оплата">{providerLabel(order.paid_with)}</Row>
      </dl>
    </Section>
  );
}

function Payments({ detail }: { detail: AdminOrderDetail }) {
  const { payments, order } = detail;
  const fromBalance = order.paid_with === "wallet";
  return (
    <Section title="Платежи" label="Платежи">
      {payments.length === 0 && (
        <p className="text-fg-muted text-sm">
          {fromBalance ? "Оплачен с баланса — платежа через кассу нет." : "Оплаты не было."}
        </p>
      )}
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
    </Section>
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
  const open = detail ? openAttention(detail) : null;

  return (
    <section className="space-y-4">
      <PageHeader
        back={{ to: "/trades", label: "Обмены" }}
        title={detail ? `Заказ ${detail.order.number}` : "Заказ"}
        badges={
          detail && (
            <>
              <OrderStatusChip
                status={detail.order.status}
                protectedUntil={detail.order.protected_until}
                estimated={detail.order.protected_estimated}
              />
              <AttentionBadge reason={open} />
            </>
          )
        }
      />
      {query.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {notFound && <p className="text-fg-muted">Заказ не найден.</p>}
      {query.isError && !notFound && (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      )}
      {detail && (
        <div className="space-y-4" data-testid="order-detail">
          {open !== null && (
            <Banner>
              Требует внимания: {ATTENTION_LABELS[open]}. Решите по ответу площадки, затем отметьте
              «Разобрано».
            </Banner>
          )}
          <OrderActions
            key={detail.order.number}
            detail={detail}
            onStale={() => {
              void query.refetch();
            }}
          />
          <DetailGrid
            main={
              <>
                <OrderFields detail={detail} />
                <div className="border-border bg-surface rounded-lg border p-4">
                  <Bought detail={detail} />
                </div>
                <Payments detail={detail} />
              </>
            }
            side={
              <>
                <MoneyFields detail={detail} />
                <Timeline detail={detail} />
              </>
            }
          />
        </div>
      )}
    </section>
  );
}
