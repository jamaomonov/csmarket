/** One account: profile, balance, history and top-ups; block, unblock, change the balance. */
import { Button } from "@csmarket/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";

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
import { useIdempotencyKey } from "./useIdempotencyKey";
import { type AdminOrderRow } from "../orders/api";
import { AttentionBadge, OrderStatusChip } from "../orders/StatusChip";

import { ApiError } from "@/lib/api";
import { formatDateTime, formatSignedSum, formatSum } from "@/lib/format";

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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="text-fg-muted w-36 shrink-0">{label}</dt>
      <dd className="min-w-0 break-all">{children}</dd>
    </div>
  );
}

function Profile({ card }: { card: AdminUserCard }) {
  const u = card.user;
  return (
    <dl className="space-y-1 text-sm">
      <Field label="Steam ID">
        <span>{u.steam_id}</span>{" "}
        <a
          href={steamProfileUrl(u.steam_id)}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:underline"
        >
          Профиль в Steam
        </a>
      </Field>
      <Field label="Email">{u.email ?? "—"}</Field>
      <Field label="Язык">{localeLabel(u.locale)}</Field>
      <Field label="Роль">{roleLabel(u.roles)}</Field>
      <Field label="Регистрация">{formatDateTime(u.created_at)}</Field>
      <Field label="Трейд-ссылка">{u.trade_link_masked ?? "не указана"}</Field>
      <Field label="Проверка ссылки">
        {tradeVerdictText(u)}
        {u.trade_link_checked_at && (
          <span className="text-fg-muted"> · {formatDateTime(u.trade_link_checked_at)}</span>
        )}
      </Field>
    </dl>
  );
}

function History({ entries }: { entries: AdminEntry[] }) {
  return (
    <section aria-labelledby="user-history" className="space-y-2">
      <h2 id="user-history" className="text-lg font-semibold">
        История баланса
      </h2>
      {entries.length === 0 && <p className="text-fg-muted text-sm">Пока пусто.</p>}
      <ul className="divide-border divide-y text-sm">
        {entries.map((e) => (
          <li key={e.id} className="flex items-start justify-between gap-4 py-2">
            <div className="min-w-0">
              <div>{kindLabel(e.kind)}</div>
              <div className="text-fg-muted">
                {formatDateTime(e.created_at)}
                {e.kind === "admin_adjust" && (
                  <>
                    {" · "}
                    <Actor actor={e.actor} />
                    {e.reason && ` · причина: ${e.reason}`}
                  </>
                )}
              </div>
            </div>
            <span className="whitespace-nowrap tabular-nums">{formatSignedSum(e.amount_uzs)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Topups({ topups }: { topups: AdminTopup[] }) {
  return (
    <section aria-labelledby="user-topups" className="space-y-2">
      <h2 id="user-topups" className="text-lg font-semibold">
        Пополнения
      </h2>
      {topups.length === 0 && <p className="text-fg-muted text-sm">Пока не было.</p>}
      {topups.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-fg-muted">
            <tr>
              <th className="py-1 font-normal">Номер</th>
              <th className="py-1 text-right font-normal">Сумма</th>
              <th className="py-1 font-normal">Статус</th>
              <th className="py-1 font-normal">Касса</th>
              <th className="py-1 font-normal">Создано</th>
            </tr>
          </thead>
          <tbody>
            {topups.map((t) => (
              <tr key={t.number} className="border-border border-t">
                <td className="py-2">
                  <Link
                    to={`/payments?q=${encodeURIComponent(t.number)}`}
                    className="font-mono hover:underline"
                  >
                    {t.number}
                  </Link>
                </td>
                <td className="whitespace-nowrap py-2 text-right tabular-nums">
                  {formatSum(t.amount_uzs)}
                </td>
                <td className="py-2">{topupStatusLabel(t.status)}</td>
                <td className="py-2">{providerLabel(t.provider)}</td>
                <td className="text-fg-muted whitespace-nowrap py-2">
                  {formatDateTime(t.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Orders({ orders }: { orders: AdminOrderRow[] }) {
  return (
    <section aria-labelledby="user-orders" className="space-y-2">
      <h2 id="user-orders" className="text-lg font-semibold">
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

type Panel = "none" | "ban" | "adjust";

function CardBody({ card }: { card: AdminUserCard }) {
  const qc = useQueryClient();
  const [panel, setPanel] = useState<Panel>("none");
  // One key per confirmed adjustment, kept across reopening the form (see useIdempotencyKey).
  // CardBody is keyed by the user id, so all of this state is per user.
  const adjustKey = useIdempotencyKey("admin-adjust");
  const banKey = useIdempotencyKey("admin-ban");
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
    <section className="space-y-6">
      <div className="flex items-center gap-4">
        {u.avatar_url && (
          <img src={u.avatar_url} alt="" width={64} height={64} className="rounded" />
        )}
        <div>
          <h1 className="text-2xl font-bold">{u.display_name ?? "Без имени"}</h1>
          {u.banned_at && (
            <p className="text-danger text-sm" data-testid="user-banned">
              Заблокирован {formatDateTime(u.banned_at)}
              {u.ban_reason && `: ${u.ban_reason}`}
            </p>
          )}
        </div>
      </div>
      <Profile card={card} />
      <p className="text-xl font-semibold tabular-nums" data-testid="user-balance">
        Баланс: {formatSum(card.balance_uzs)}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          variant={banned ? "secondary" : "danger"}
          onClick={() => {
            open("ban");
          }}
        >
          {banned ? "Разблокировать" : "Заблокировать"}
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            open("adjust");
          }}
        >
          Изменить баланс
        </Button>
      </div>
      {notice !== null && (
        <p role="alert" className="text-danger text-sm">
          {notice}
        </p>
      )}
      {panel === "adjust" && (
        <AdjustForm userId={u.id} idem={adjustKey} onDone={changed} onClose={close} />
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
      <History entries={card.entries} />
      <Orders orders={card.orders} />
      <Topups topups={card.topups} />
    </section>
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
