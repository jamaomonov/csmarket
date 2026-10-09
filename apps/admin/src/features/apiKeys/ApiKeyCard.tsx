/** One API key: owner, tariff, sales, webhook host, latest orders; switch the tariff, revoke. */
import { Button } from "@csmarket/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  type AdminApiKeyCard,
  getApiKeyCard,
  revokeApiKey,
  setApiKeyTariff,
  type Tariff,
} from "./api";
import { deliveryLabel, errorText, tariffLabel } from "./labels";
import { ReasonDialog } from "./ReasonDialog";
import { type AdminOrderRow } from "../orders/api";
import { AttentionBadge, OrderStatusChip } from "../orders/StatusChip";
import { useIdempotencyKey } from "../users/useIdempotencyKey";

import { ApiError } from "@/lib/api";
import { formatDateTime, formatSum, formatUsd } from "@/lib/format";

const cardKey = (id: string) => ["admin", "api-keys", "card", id] as const;

function Orders({ orders }: { orders: AdminOrderRow[] }) {
  return (
    <section aria-labelledby="key-orders" className="space-y-2">
      <h2 id="key-orders" className="text-lg font-semibold">
        Заказы
      </h2>
      {orders.length === 0 && <p className="text-fg-muted text-sm">Пока не было.</p>}
      {orders.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-fg-muted">
            <tr>
              <th className="py-1 font-normal">Номер</th>
              <th className="py-1 font-normal">Скин</th>
              <th className="py-1 text-right font-normal">Цена</th>
              <th className="py-1 font-normal">Статус</th>
              <th className="py-1 font-normal">Создан</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.number} className="border-border border-t">
                <td className="py-2">
                  <Link to={`/orders/${o.number}`} className="font-mono hover:underline">
                    {o.number}
                  </Link>
                </td>
                <td className="py-2 pr-3">{o.name}</td>
                <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
                  {formatSum(o.price_uzs)}
                </td>
                <td className="py-2 pr-3">
                  <div className="flex flex-wrap items-center gap-1">
                    <OrderStatusChip status={o.status} />
                    <AttentionBadge reason={o.attention_reason} />
                  </div>
                </td>
                <td className="text-fg-muted whitespace-nowrap py-2">
                  {formatDateTime(o.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

type Panel = "none" | "tariff" | "revoke";

function CardBody({ card }: { card: AdminApiKeyCard }) {
  const qc = useQueryClient();
  const [panel, setPanel] = useState<Panel>("none");
  const tariffKey = useIdempotencyKey("admin-key-tariff");
  const revokeKey = useIdempotencyKey("admin-key-revoke");
  const k = card.key;
  const revoked = k.revoked_at !== null;
  const target: Tariff = k.pricing_profile === "cost" ? "retail" : "cost";
  const hook = card.webhook;
  const done = (next: AdminApiKeyCard) => {
    qc.setQueryData(cardKey(k.id), next);
    void qc.invalidateQueries({ queryKey: ["admin", "api-keys", "list"] });
    setPanel("none");
  };
  const close = () => {
    setPanel("none");
  };

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{k.user.display_name ?? "Без имени"}</h1>
        <p className="text-sm">
          <Link to={`/users/${k.user.id}`} className="text-accent hover:underline">
            Карточка пользователя
          </Link>
        </p>
        {revoked && (
          <p className="text-danger text-sm" data-testid="key-revoked">
            Отозван {formatDateTime(k.revoked_at ?? "")}
          </p>
        )}
      </div>
      <dl className="space-y-1 text-sm">
        <div className="flex gap-3">
          <dt className="text-fg-muted w-36 shrink-0">Тариф</dt>
          <dd data-testid="key-tariff">{tariffLabel(k.pricing_profile)}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="text-fg-muted w-36 shrink-0">Заказы</dt>
          <dd>{k.orders}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="text-fg-muted w-36 shrink-0">Выручка</dt>
          <dd className="tabular-nums">{formatUsd(k.revenue_usd)}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="text-fg-muted w-36 shrink-0">Себестоимость</dt>
          <dd className="tabular-nums">{formatUsd(k.cost_usd)}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="text-fg-muted w-36 shrink-0">Создан</dt>
          <dd>{formatDateTime(k.created_at)}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="text-fg-muted w-36 shrink-0">Был в сети</dt>
          <dd>{k.last_used_at ? formatDateTime(k.last_used_at) : "—"}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="text-fg-muted w-36 shrink-0">Вебхук</dt>
          <dd data-testid="key-webhook">
            {hook === null ? (
              "не задан"
            ) : (
              <>
                {hook.host}
                {hook.last_delivery && (
                  <span className="text-fg-muted">
                    {" · "}
                    {deliveryLabel(hook.last_delivery.status)},{" "}
                    {formatDateTime(hook.last_delivery.created_at)}
                  </span>
                )}
              </>
            )}
          </dd>
        </div>
      </dl>
      {!revoked && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            onClick={() => {
              setPanel("tariff");
            }}
          >
            {target === "cost" ? "Тариф: по себестоимости" : "Тариф: розница"}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              setPanel("revoke");
            }}
          >
            Отозвать ключ
          </Button>
        </div>
      )}
      {panel === "tariff" && (
        <ReasonDialog
          key={target}
          title={target === "cost" ? "Тариф по себестоимости" : "Тариф «розница»"}
          description="Новые заказы пойдут по этому тарифу. Уже оформленные останутся по своей цене."
          confirmLabel="Переключить"
          identity={`tariff:${k.id}:${target}`}
          idem={tariffKey}
          run={(reason, key) => setApiKeyTariff(k.id, target, reason, key)}
          onDone={done}
          onClose={close}
        />
      )}
      {panel === "revoke" && (
        <ReasonDialog
          title="Отозвать ключ"
          description="Ключ перестанет работать сразу. Владелец сможет выпустить новый."
          confirmLabel="Отозвать"
          danger
          identity={`revoke:${k.id}`}
          idem={revokeKey}
          run={(reason, key) => revokeApiKey(k.id, reason, key)}
          onDone={done}
          onClose={close}
        />
      )}
      <Orders orders={card.orders} />
    </section>
  );
}

export function ApiKeyCard() {
  const { id = "" } = useParams();
  const card = useQuery({ queryKey: cardKey(id), queryFn: () => getApiKeyCard(id) });
  if (card.isPending) return <p className="text-fg-muted">Загрузка…</p>;
  if (card.isError) {
    const missing = card.error instanceof ApiError && card.error.status === 404;
    return (
      <p role="alert" className={missing ? "text-fg-muted" : "text-danger"}>
        {missing ? "Ключ не найден." : errorText(card.error)}
      </p>
    );
  }
  return <CardBody key={id} card={card.data} />;
}
