/**
 * «Заказ». The header names the skin with its picture and price; an open attention is a banner
 * under it. The actions sit in the header on a wide screen and in a bar at the bottom of a
 * phone's screen. A phone reads banner → summary → actions → details (admin UX audit §4); ids
 * to search a market's cabinet by are folded under «Подробнее».
 */
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { type AdminOrderDetail, getOrder } from "./api";
import { AttentionBadge } from "./AttentionBadge";
import { detailKey } from "./keys";
import { type AttentionReason } from "./kinds";
import { orderChip } from "./labels";
import { LisskinsBlock } from "./LisskinsBlock";
import { useOrderActions } from "./OrderActions";
import { SkinslinkBlock } from "./SkinslinkBlock";
import { TradeBlock } from "./TradeBlock";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { ActionBar, Banner, DetailGrid, More, Row, Section } from "@/components/Section";
import { Reason, Status } from "@/components/Status";
import { TradeLinkValue } from "@/components/SteamLinks";
import { TextLink } from "@/components/TextLink";
import { UserCell } from "@/components/UserCell";
import { errorText, providerLabel } from "@/features/users/labels";
import { ApiError } from "@/lib/api";
import { reasonText } from "@/lib/dictionary";
import { formatDateTime, formatRate, formatSum } from "@/lib/format";
import { useNarrow } from "@/lib/useNarrow";

const SOURCE_LABELS: Record<AdminOrderDetail["order"]["source"], string> = {
  waxpeer: "Waxpeer",
  skinslink: "Skinslink",
  lisskins: "LIS-SKINS",
};

/** The market's side of the order: a purchase block, or the Waxpeer trade. */
function Bought({ detail }: { detail: AdminOrderDetail }) {
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

/** The header's line: the skin's picture, its name and what the buyer paid. */
function HeaderSkin({ detail }: { detail: AdminOrderDetail }) {
  const { order } = detail;
  return (
    <span className="flex min-w-0 items-center gap-2" data-testid="order-header-skin">
      {order.image_url ? (
        <img
          src={order.image_url}
          alt=""
          width={40}
          height={30}
          className="h-[30px] w-10 shrink-0 object-contain"
        />
      ) : null}
      <span className="min-w-0 truncate">{order.market_hash_name}</span>
      <Money uzs={order.price_uzs} className="text-fg shrink-0 font-semibold" />
    </span>
  );
}

function Summary({ detail }: { detail: AdminOrderDetail }) {
  const { order, user } = detail;
  return (
    <Section title="Заказ">
      <dl>
        <Row label="Скин">
          {order.market_hash_name}
          {order.phase !== null && <span className="text-fg-muted"> · {order.phase}</span>}
        </Row>
        <Row label="Цена">
          <Money uzs={order.price_uzs} className="font-semibold" />
          <span className="text-fg-muted">
            {" · "}
            <Money usd={order.price_usd} />
          </span>
        </Row>
        <Row label="Пользователь">
          <UserCell id={user.id} name={user.display_name} avatarUrl={user.avatar_url} />
        </Row>
        <Row label="Оплата">{providerLabel(order.paid_with)}</Row>
        <Row label="Источник">{SOURCE_LABELS[order.source]}</Row>
        <Row label="Трейд-ссылка">
          <TradeLinkValue link={order.trade_link} />
        </Row>
      </dl>
      {order.offer_id !== null && (
        <More>
          <Row label="Предложение">{order.offer_id}</Row>
        </More>
      )}
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
            {order.failure_reason !== null && (
              <>
                {" · "}
                <Reason of="failure" code={order.failure_reason} />
              </>
            )}
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
        <Row label="Курс">{formatRate(order.fx_rate)}</Row>
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
            <TextLink to={`/payments/${p.id}`}>
              {providerLabel(p.provider)} · {formatSum(p.amount_uzs)}
            </TextLink>
            <Status of="payment" code={p.status} />
            <span className="text-fg-muted">{formatDateTime(p.created_at)}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function OrderBody({ detail, onStale }: { detail: AdminOrderDetail; onStale: () => void }) {
  const narrow = useNarrow();
  const actions = useOrderActions(detail, onStale);
  const open = openAttention(detail);
  const { order } = detail;
  const bar =
    actions.buttons === null ? null : (
      <ActionBar label="Действия" testId="order-actions">
        {actions.buttons}
      </ActionBar>
    );
  return (
    <section className="space-y-4">
      <PageHeader
        back={{ to: "/trades", label: "Обмены" }}
        title={`Заказ ${order.number}`}
        badges={
          <>
            <Status
              {...orderChip(order.status, order.protected_until, order.protected_estimated)}
              testId="order-status"
            />
            <AttentionBadge reason={open} />
          </>
        }
        meta={<HeaderSkin detail={detail} />}
        {...(!narrow && bar !== null && { actions: bar })}
      />
      <div className="space-y-4" data-testid="order-detail">
        {open !== null && (
          <Banner>
            Требует внимания: {reasonText("orderAttention", open)}. Решите по ответу площадки, затем
            отметьте «Разобрано».
          </Banner>
        )}
        {actions.panel}
        {narrow ? (
          <>
            <Summary detail={detail} />
            {bar}
            <Bought detail={detail} />
            <MoneyFields detail={detail} />
            <Payments detail={detail} />
            <Timeline detail={detail} />
          </>
        ) : (
          <DetailGrid
            main={
              <>
                <Summary detail={detail} />
                <Bought detail={detail} />
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
        )}
      </div>
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
  if (detail) {
    return (
      <OrderBody
        key={detail.order.number}
        detail={detail}
        onStale={() => {
          void query.refetch();
        }}
      />
    );
  }
  return (
    <section className="space-y-4">
      <PageHeader back={{ to: "/trades", label: "Обмены" }} title="Заказ" />
      {query.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {notFound && <p className="text-fg-muted">Заказ не найден.</p>}
      {query.isError && !notFound && (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      )}
    </section>
  );
}
