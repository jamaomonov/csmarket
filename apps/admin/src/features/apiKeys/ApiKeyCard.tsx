/**
 * A user's API key, shown as the «API-ключ» tab of the user card (owner, 2026-10-09: no
 * separate page): tariff, sales, limits, IP allow-list, webhook, the key's orders; switch the
 * tariff, edit limits, revoke. `/api-keys/:id` redirects to the owner's card.
 */
import { Button } from "@csmarket/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useParams } from "react-router-dom";

import {
  type AdminApiKeyCard,
  getApiKeyCard,
  revokeApiKey,
  setApiKeyTariff,
  type Tariff,
} from "./api";
import { deliveryLabel, errorText, LIMIT_LABELS, LIMIT_NAMES, tariffLabel } from "./labels";
import { LimitsForm } from "./LimitsForm";
import { ReasonDialog } from "./ReasonDialog";
import { OrdersTable } from "../orders/OrdersTable";
import { useIdempotencyKey } from "../users/useIdempotencyKey";

import { EmptyState } from "@/components/EmptyState";
import { Modal } from "@/components/Modal";
import { Money } from "@/components/Money";
import { Banner, DetailGrid, Row, Section } from "@/components/Section";
import { ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export const apiKeyCardKey = (id: string) => ["admin", "api-keys", "card", id] as const;

type Panel = "none" | "tariff" | "revoke" | "limits";

function KeyBody({ card }: { card: AdminApiKeyCard }) {
  const qc = useQueryClient();
  const [panel, setPanel] = useState<Panel>("none");
  const tariffKey = useIdempotencyKey("admin-key-tariff");
  const revokeKey = useIdempotencyKey("admin-key-revoke");
  const limitsKey = useIdempotencyKey("admin-key-limits");
  const k = card.key;
  const revoked = k.revoked_at !== null;
  const target: Tariff = k.pricing_profile === "cost" ? "retail" : "cost";
  const hook = card.webhook;
  const done = (next: AdminApiKeyCard) => {
    qc.setQueryData(apiKeyCardKey(k.id), next);
    void qc.invalidateQueries({ queryKey: ["admin", "users"] });
    setPanel("none");
  };
  const close = () => {
    setPanel("none");
  };

  const main = (
    <>
      <Section
        title="Ключ"
        actions={
          !revoked && (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setPanel("tariff");
                }}
              >
                {target === "cost" ? "На себестоимость" : "На розницу"}
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  setPanel("revoke");
                }}
              >
                Отозвать
              </Button>
            </div>
          )
        }
      >
        <dl>
          <Row label="Тариф">
            <span data-testid="key-tariff">{tariffLabel(k.pricing_profile)}</span>
          </Row>
          <Row label="Заказы">{k.orders}</Row>
          <Row label="Выручка">
            <Money usd={k.revenue_usd} />
          </Row>
          <Row label="Себестоимость">
            <Money usd={k.cost_usd} />
          </Row>
          <Row label="Выпущен">{formatDateTime(k.created_at)}</Row>
          <Row label="Последний запрос">
            {k.last_used_at ? formatDateTime(k.last_used_at) : "—"}
          </Row>
          <Row label="Вебхук">
            <span data-testid="key-webhook">
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
            </span>
          </Row>
          <Row label="IP-адреса">
            <span data-testid="key-allowlist">
              {k.ip_allowlist.length === 0 ? "любой адрес" : k.ip_allowlist.join(", ")}
            </span>
          </Row>
        </dl>
      </Section>
      <Section title="Заказы через ключ">
        <OrdersTable orders={card.orders} label="Заказы через ключ" />
      </Section>
    </>
  );

  const side = (
    <Section
      title="Лимиты в минуту"
      actions={
        !revoked && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setPanel("limits");
            }}
          >
            Изменить
          </Button>
        )
      }
    >
      <dl data-testid="key-limits">
        {LIMIT_NAMES.map((name) => (
          <Row key={name} label={LIMIT_LABELS[name]}>
            <span className="tabular-nums">{k.limits[name]}</span>
            {!k.custom_limits.includes(name) && (
              <span className="text-fg-muted"> · по умолчанию</span>
            )}
          </Row>
        ))}
      </dl>
    </Section>
  );

  return (
    <div className="space-y-4">
      {revoked && (
        <Banner>
          <span data-testid="key-revoked">Ключ отозван {formatDateTime(k.revoked_at ?? "")}</span>
        </Banner>
      )}
      <DetailGrid main={main} side={side} />
      {panel === "limits" && (
        <Modal title="Лимиты в минуту" onClose={close}>
          <LimitsForm
            keyId={k.id}
            current={Object.fromEntries(k.custom_limits.map((n) => [n, k.limits[n]]))}
            idem={limitsKey}
            onDone={done}
            onClose={close}
          />
        </Modal>
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
    </div>
  );
}

/** The key's tab on its owner's card. */
export function ApiKeyPanel({ keyId }: { keyId: string }) {
  const card = useQuery({ queryKey: apiKeyCardKey(keyId), queryFn: () => getApiKeyCard(keyId) });
  if (card.isPending) return <p className="text-fg-muted text-sm">Загрузка…</p>;
  if (card.isError) return <EmptyState tone="danger">{errorText(card.error)}</EmptyState>;
  return <KeyBody key={keyId} card={card.data} />;
}

/** `/api-keys/:id` → the owner's card, on the «API-ключ» tab. */
export function ApiKeyRedirect() {
  const { id = "" } = useParams();
  const card = useQuery({ queryKey: apiKeyCardKey(id), queryFn: () => getApiKeyCard(id) });
  if (card.isPending) return <p className="text-fg-muted">Загрузка…</p>;
  if (card.isError) {
    const missing = card.error instanceof ApiError && card.error.status === 404;
    return (
      <p role="alert" className={missing ? "text-fg-muted" : "text-danger"}>
        {missing ? "Ключ не найден." : errorText(card.error)}
      </p>
    );
  }
  return <Navigate to={`/users/${card.data.key.user.id}?tab=api`} replace />;
}
