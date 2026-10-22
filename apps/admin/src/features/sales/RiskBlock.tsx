/**
 * «Риски» on a payout: the seller's Steam profile, account age, ban / frozen wallet, the sell
 * block (with a toggle), totals sold and paid, sales of the last 24 h, and other accounts that
 * saved the same card (matched by a keyed fingerprint, never by the number). What needs a look
 * is red and on top; the rest folds away.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { setSellBlock } from "./api";
import { payoutKey, SELL_BLOCKS_KEY } from "./keys";
import { payoutErrorText } from "./labels";
import { type PayoutDetail as Detail, type PayoutRisk } from "./payoutsApi";

import { Money } from "@/components/Money";
import { More, Row, Section } from "@/components/Section";
import { LINK } from "@/components/TextLink";
import { UserCell } from "@/components/UserCell";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

const DAY = 86_400_000;

function age(iso: string | null): string {
  if (iso === null) return "—";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / DAY);
  return `${String(days)} дн. (с ${formatDateTime(iso).slice(0, 10)})`;
}

function SellBlockToggle({ detail, risk }: { detail: Detail; risk: PayoutRisk }) {
  const qc = useQueryClient();
  const userId = detail.request.user.id;
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const key = useIdempotencyKey("admin-sell-block");
  const toggle = useMutation({
    mutationFn: (blocked: boolean) =>
      setSellBlock(
        userId,
        blocked,
        blocked ? reason.trim() : null,
        key.keyFor(JSON.stringify({ userId, blocked, reason })),
      ),
    onSuccess: () => {
      key.reset();
      setAsking(false);
      setReason("");
      void qc.invalidateQueries({ queryKey: payoutKey(detail.request.id) });
      void qc.invalidateQueries({ queryKey: SELL_BLOCKS_KEY });
    },
  });
  return (
    <div className="space-y-2">
      {risk.sell_blocked ? (
        <Button
          variant="secondary"
          size="sm"
          disabled={toggle.isPending}
          onClick={() => {
            toggle.mutate(false);
          }}
        >
          Разрешить выкуп
        </Button>
      ) : asking ? (
        <div className="space-y-2">
          <label className="flex flex-col gap-1 text-sm">
            Причина запрета (пользователь её не увидит)
            <input
              value={reason}
              maxLength={500}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              className="border-border bg-bg rounded-md border px-3 py-1.5"
            />
          </label>
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={toggle.isPending || reason.trim() === ""}
              onClick={() => {
                toggle.mutate(true);
              }}
            >
              Да, запретить
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setAsking(false);
              }}
            >
              Отмена
            </Button>
          </div>
        </div>
      ) : (
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            setAsking(true);
          }}
        >
          Запретить выкуп
        </Button>
      )}
      {toggle.isError ? (
        <p role="alert" className="text-danger text-sm">
          {payoutErrorText(toggle.error)}
        </p>
      ) : null}
    </div>
  );
}

interface RiskRow {
  key: string;
  label: string;
  value: ReactNode;
  /** Red, on top; the rest fold under «Всё в порядке: N». */
  alarm: boolean;
  /** Not known to be fine (an old card's fingerprint): amber, on top, never folded. */
  warn?: boolean;
}

function SharedCard({ risk }: { risk: PayoutRisk }) {
  if (!risk.card_known) return <>неизвестно (карта старая, отпечаток ещё не посчитан)</>;
  if (risk.shared_card_users.length === 0) return <>нет</>;
  return (
    <ul>
      {risk.shared_card_users.map((u) => (
        <li key={u.id}>
          <UserCell id={u.id} name={u.display_name} avatarUrl={u.avatar_url} />
        </li>
      ))}
    </ul>
  );
}

function riskRows(risk: PayoutRisk, newAccount: boolean): RiskRow[] {
  const steam = risk.steam_url ? (
    <a href={risk.steam_url} target="_blank" rel="noreferrer" className={LINK}>
      профиль Steam
    </a>
  ) : (
    "—"
  );
  return [
    {
      key: "ban",
      label: "Блокировка",
      value: risk.banned ? `заблокирован${risk.ban_reason ? `: ${risk.ban_reason}` : ""}` : "нет",
      alarm: risk.banned,
    },
    {
      key: "wallet",
      label: "Кошелёк",
      value: risk.wallet_frozen ? "заморожен" : "активен",
      alarm: risk.wallet_frozen,
    },
    {
      key: "sell",
      label: "Выкуп",
      value: risk.sell_blocked
        ? `запрещён${risk.sell_block_reason ? `: ${risk.sell_block_reason}` : ""}`
        : "разрешён",
      alarm: risk.sell_blocked,
    },
    {
      key: "card",
      label: "Та же карта у других",
      value: <SharedCard risk={risk} />,
      alarm: risk.card_known && risk.shared_card_users.length > 0,
      warn: !risk.card_known,
    },
    { key: "age", label: "Аккаунт у нас", value: age(risk.account_created_at), alarm: newAccount },
    { key: "steam", label: "Steam", value: steam, alarm: false },
    {
      key: "sold",
      label: "Продано всего",
      value: (
        <>
          {risk.sold_count} · <Money uzs={risk.sold_uzs} />
        </>
      ),
      alarm: false,
    },
    {
      key: "paid",
      label: "Выплачено на карты",
      value: (
        <>
          {risk.paid_count} · <Money uzs={risk.paid_uzs} />
        </>
      ),
      alarm: false,
    },
    {
      key: "card-paid",
      label: "На эту карту",
      value: (
        <>
          <Money uzs={risk.card_paid_uzs} /> (все аккаунты)
        </>
      ),
      alarm: false,
    },
    {
      key: "day",
      label: "Продаж за 24 ч",
      value: (
        <>
          {risk.day_count} · <Money usd={risk.day_usd} />
        </>
      ),
      alarm: false,
    },
  ];
}

/**
 * «Риски»: what needs a look on top in red; everything else folded under «Всё в порядке: N»,
 * so eleven rows of one weight never hide the one that matters.
 */
export function RiskBlock({ detail }: { detail: Detail }) {
  const risk = detail.risk ?? null;
  if (risk === null) return null;
  const rows = riskRows(risk, (detail.request.flags ?? []).includes("new_account"));
  const alarms = rows.filter((r) => r.alarm);
  const warnings = rows.filter((r) => !r.alarm && r.warn === true);
  const calm = rows.filter((r) => !r.alarm && r.warn !== true);
  return (
    <Section title="Риски">
      {alarms.length > 0 ? (
        <dl data-testid="risk-alarms">
          {alarms.map((r) => (
            <Row key={r.key} label={r.label}>
              <span className="text-danger font-semibold">{r.value}</span>
            </Row>
          ))}
        </dl>
      ) : warnings.length === 0 ? (
        <p className="text-success text-sm">Рисков не видно.</p>
      ) : null}
      {warnings.length > 0 && (
        <dl data-testid="risk-warnings">
          {warnings.map((r) => (
            <Row key={r.key} label={r.label}>
              <span className="text-warning">{r.value}</span>
            </Row>
          ))}
        </dl>
      )}
      <More label={`Всё в порядке: ${String(calm.length)}`}>
        {calm.map((r) => (
          <Row key={r.key} label={r.label}>
            {r.value}
          </Row>
        ))}
      </More>
      <div className="mt-3">
        <SellBlockToggle detail={detail} risk={risk} />
      </div>
    </Section>
  );
}
