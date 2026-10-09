/** One account: profile, balance, history and top-ups; block, unblock, change the balance. */
import { Button } from "@csmarket/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { AdjustForm } from "./AdjustForm";
import { type AdminEntry, type AdminTopup, type AdminUserCard, getUserCard } from "./api";
import { BanDialog } from "./BanDialog";
import {
  errorText,
  kindLabel,
  localeLabel,
  providerLabel,
  roleLabel,
  topupStatusLabel,
  tradeVerdictText,
} from "./labels";
import { UsdSwitchDialog } from "./UsdSwitchDialog";
import { useIdempotencyKey } from "./useIdempotencyKey";
import { ApiKeyPanel } from "../apiKeys/ApiKeyCard";
import { type AdminOrderRow } from "../orders/api";
import { OrdersTable } from "../orders/OrdersTable";

import { DataTable } from "@/components/DataTable";
import { Modal } from "@/components/Modal";
import { Money } from "@/components/Money";
import { MoreMenu } from "@/components/MoreMenu";
import { PageHeader } from "@/components/PageHeader";
import { Banner, DetailGrid, Row, Section } from "@/components/Section";
import { StatusChip } from "@/components/StatusChip";
import { Tabs } from "@/components/Tabs";
import { ApiError } from "@/lib/api";
import {
  formatDateTime,
  formatSignedSum,
  formatSignedUsd,
  formatSum,
  formatUsd,
} from "@/lib/format";

const cardKey = (id: string) => ["admin", "users", "card", id] as const;

function steamProfileUrl(steamId: string): string {
  return `https://steamcommunity.com/profiles/${encodeURIComponent(steamId)}`;
}

/** `admin:<uuid>` → a link to that admin's card; anything else is not shown. */
function Actor({ actor }: { actor: string | null }) {
  if (!actor?.startsWith("admin:")) return null;
  return (
    <>
      кто:{" "}
      <Link to={`/users/${actor.slice("admin:".length)}`} className="hover:underline">
        администратор
      </Link>
    </>
  );
}

function Profile({ card }: { card: AdminUserCard }) {
  const u = card.user;
  return (
    <dl>
      <Row label="Steam ID">
        <span>{u.steam_id}</span>{" "}
        <a
          href={steamProfileUrl(u.steam_id)}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:underline"
        >
          Профиль в Steam
        </a>
      </Row>
      <Row label="Email">{u.email ?? "—"}</Row>
      <Row label="Язык">{localeLabel(u.locale)}</Row>
      <Row label="Роль">{roleLabel(u.roles)}</Row>
      <Row label="Регистрация">{formatDateTime(u.created_at)}</Row>
      <Row label="Трейд-ссылка">{u.trade_link_masked ?? "не указана"}</Row>
      <Row label="Проверка ссылки">
        {tradeVerdictText(u)}
        {u.trade_link_checked_at && (
          <span className="text-fg-muted"> · {formatDateTime(u.trade_link_checked_at)}</span>
        )}
      </Row>
    </dl>
  );
}

function entryAmount(e: AdminEntry): string {
  return e.amount_usd !== null ? formatSignedUsd(e.amount_usd) : formatSignedSum(e.amount_uzs);
}

function History({ entries, id, title }: { entries: AdminEntry[]; id: string; title: string }) {
  return (
    <Section title={title} label={title}>
      {entries.length === 0 && <p className="text-fg-muted text-sm">Пока пусто.</p>}
      <ul id={id} className="divide-border divide-y text-sm">
        {entries.map((e) => (
          <li key={e.id} className="flex items-start justify-between gap-4 py-2">
            <div className="min-w-0">
              <div>{kindLabel(e.kind)}</div>
              <div className="text-fg-muted">
                {formatDateTime(e.created_at)}
                {(e.kind === "admin_adjust" || e.kind === "admin_adjust_usd") && (
                  <>
                    {" · "}
                    <Actor actor={e.actor} />
                    {e.reason && ` · причина: ${e.reason}`}
                  </>
                )}
              </div>
            </div>
            <span className="whitespace-nowrap tabular-nums">{entryAmount(e)}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Topups({ topups }: { topups: AdminTopup[] }) {
  return (
    <Section title="Пополнения">
      <DataTable
        label="Пополнения"
        rows={topups}
        rowKey={(t) => t.number}
        empty="Пока не было."
        columns={[
          {
            key: "number",
            header: "Номер",
            cell: (t) => (
              <Link
                to={`/payments?q=${encodeURIComponent(t.number)}`}
                className="font-mono hover:underline"
              >
                {t.number}
              </Link>
            ),
          },
          {
            key: "sum",
            header: "Сумма",
            align: "right",
            cell: (t) => <Money uzs={t.amount_uzs} />,
          },
          { key: "status", header: "Статус", cell: (t) => topupStatusLabel(t.status) },
          { key: "kassa", header: "Касса", cell: (t) => providerLabel(t.provider) },
          {
            key: "created",
            header: "Создано",
            cell: (t) => (
              <span className="text-fg-muted whitespace-nowrap">
                {formatDateTime(t.created_at)}
              </span>
            ),
          },
        ]}
      />
    </Section>
  );
}

function Orders({ orders }: { orders: AdminOrderRow[] }) {
  return (
    <Section title="Заказы">
      <OrdersTable orders={orders} label="Заказы пользователя" />
    </Section>
  );
}

type Panel = "none" | "ban" | "adjust" | "usd";
type Tab = "overview" | "api";

function UsdBlock({ card, onSwitch }: { card: AdminUserCard; onSwitch: () => void }) {
  const on = card.usd_wallet_enabled;
  return (
    <Section title="USD-кошелёк">
      <div className="space-y-3" data-testid="usd-block">
        <div className="flex items-center gap-2 text-sm">
          <StatusChip tone={on ? "success" : "muted"}>{on ? "включён" : "выключен"}</StatusChip>
        </div>
        <p className="text-lg font-semibold tabular-nums" data-testid="user-balance-usd">
          Баланс: {formatUsd(card.balance_usd)}
        </p>
        <Button size="sm" variant={on ? "danger" : "secondary"} onClick={onSwitch}>
          {on ? "Выключить USD-кошелёк" : "Включить USD-кошелёк"}
        </Button>
      </div>
    </Section>
  );
}

function Overview({ card, onUsd }: { card: AdminUserCard; onUsd: () => void }) {
  const main = (
    <>
      <History entries={card.entries} id="user-history" title="История баланса" />
      {(card.usd_wallet_enabled || card.usd_entries.length > 0) && (
        <History entries={card.usd_entries} id="user-history-usd" title="История USD" />
      )}
      <Orders orders={card.orders} />
      <Topups topups={card.topups} />
    </>
  );
  const side = (
    <>
      <Section title="Профиль">
        <Profile card={card} />
      </Section>
      <UsdBlock card={card} onSwitch={onUsd} />
    </>
  );
  return <DetailGrid main={main} side={side} />;
}

function CardBody({ card }: { card: AdminUserCard }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "api" && card.api_key_id !== null ? "api" : "overview";
  const [panel, setPanel] = useState<Panel>("none");
  // One key per confirmed adjustment, kept across reopening the form (see useIdempotencyKey).
  // CardBody is keyed by the user id, so all of this state is per user.
  const adjustKey = useIdempotencyKey("admin-adjust");
  const banKey = useIdempotencyKey("admin-ban");
  const usdKey = useIdempotencyKey("admin-usd-switch");
  const unbanKey = useIdempotencyKey("admin-unban");
  const [notice, setNotice] = useState<string | null>(null);
  const u = card.user;
  const banned = u.banned_at !== null;
  const open = (next: Panel) => {
    setNotice(null);
    setPanel(next);
  };
  const changed = (next: AdminUserCard) => {
    qc.setQueryData(cardKey(u.id), next);
    void qc.invalidateQueries({ queryKey: ["admin", "users", "list"] });
    setPanel("none");
  };
  const stale = (message: string) => {
    setPanel("none");
    setNotice(message);
    void qc.invalidateQueries({ queryKey: cardKey(u.id) });
  };
  const close = () => {
    setPanel("none");
  };

  return (
    <section className="space-y-4">
      <div className="flex items-start gap-4">
        {u.avatar_url && (
          <img src={u.avatar_url} alt="" width={56} height={56} className="rounded-lg" />
        )}
        <div className="min-w-0 flex-1">
          <PageHeader
            back={{ to: "/users", label: "Пользователи" }}
            title={u.display_name ?? "Без имени"}
            badges={
              <>
                {u.roles.includes("admin") && <StatusChip tone="info">админ</StatusChip>}
                {banned && <StatusChip tone="danger">заблокирован</StatusChip>}
                {card.api_key_id !== null && <StatusChip tone="neutral">API</StatusChip>}
              </>
            }
            actions={
              <>
                <Button
                  variant="secondary"
                  onClick={() => {
                    open("adjust");
                  }}
                >
                  Изменить баланс
                </Button>
                <MoreMenu
                  actions={[
                    {
                      key: "ban",
                      label: banned ? "Разблокировать" : "Заблокировать",
                      danger: !banned,
                      onSelect: () => {
                        open("ban");
                      },
                    },
                  ]}
                />
              </>
            }
          />
        </div>
      </div>
      {u.banned_at && (
        <Banner>
          <span data-testid="user-banned">
            Заблокирован {formatDateTime(u.banned_at)}
            {u.ban_reason && `: ${u.ban_reason}`}
          </span>
        </Banner>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Баланс">
          <span data-testid="user-balance">Баланс: {formatSum(card.balance_uzs)}</span>
        </Tile>
        <Tile label="USD">
          <Money usd={card.balance_usd} digits={3} />
        </Tile>
        <Tile label="Заказов (последние)">{card.orders.length}</Tile>
        <Tile label="Пополнений (последние)">{card.topups.length}</Tile>
      </div>
      {notice !== null && (
        <p role="alert" className="text-danger text-sm">
          {notice}
        </p>
      )}
      {card.api_key_id !== null && (
        <Tabs<Tab>
          label="Разделы"
          value={tab}
          onChange={(next) => {
            const nextParams = new URLSearchParams(params);
            if (next === "api") nextParams.set("tab", "api");
            else nextParams.delete("tab");
            setParams(nextParams, { replace: true });
          }}
          items={[
            { key: "overview", label: "Обзор" },
            { key: "api", label: "API-ключ" },
          ]}
        />
      )}
      {tab === "api" && card.api_key_id !== null ? (
        <ApiKeyPanel keyId={card.api_key_id} />
      ) : (
        <Overview
          card={card}
          onUsd={() => {
            open("usd");
          }}
        />
      )}
      {panel === "adjust" && (
        <Modal title="Изменить баланс" onClose={close} wide>
          <AdjustForm userId={u.id} idem={adjustKey} onDone={changed} onClose={close} />
        </Modal>
      )}
      {panel === "usd" && (
        <UsdSwitchDialog
          key={String(card.usd_wallet_enabled)}
          userId={u.id}
          enable={!card.usd_wallet_enabled}
          idem={usdKey}
          onDone={changed}
          onClose={close}
        />
      )}
      {panel === "ban" && (
        <BanDialog
          key={String(banned)}
          userId={u.id}
          banned={banned}
          idem={banned ? unbanKey : banKey}
          onDone={changed}
          onStale={stale}
          onClose={close}
        />
      )}
    </section>
  );
}

function Tile({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-border bg-surface rounded-lg border px-4 py-3">
      <div className="text-fg-muted text-xs">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{children}</div>
    </div>
  );
}

export function UserCard() {
  const { id = "" } = useParams();
  const card = useQuery({ queryKey: cardKey(id), queryFn: () => getUserCard(id) });
  if (card.isPending) return <p className="text-fg-muted">Загрузка…</p>;
  if (card.isError) {
    const missing = card.error instanceof ApiError && card.error.status === 404;
    return (
      <p role="alert" className={missing ? "text-fg-muted" : "text-danger"}>
        {missing ? "Пользователь не найден." : errorText(card.error)}
      </p>
    );
  }
  // Keyed by the route id: another user's card never inherits a draft, dialog or key.
  return <CardBody key={id} card={card.data} />;
}
