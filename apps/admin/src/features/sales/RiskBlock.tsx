/**
 * «Риски» on a payout: the seller's Steam profile, account age, ban / frozen wallet, the sell
 * block (with a toggle), totals sold and paid, sales of the last 24 h, and other accounts that
 * saved the same card (matched by a keyed fingerprint, never by the number).
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { setSellBlock } from "./api";
import { payoutKey, SELL_BLOCKS_KEY } from "./keys";
import { payoutErrorText } from "./labels";
import { type PayoutDetail as Detail, type PayoutRisk } from "./payoutsApi";

import { Money } from "@/components/Money";
import { Row, Section } from "@/components/Section";
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

export function RiskBlock({ detail }: { detail: Detail }) {
  const risk = detail.risk ?? null;
  if (risk === null) return null;
  const danger = "text-danger font-semibold";
  return (
    <Section title="Риски">
      <dl>
        <Row label="Steam">
          {risk.steam_url ? (
            <a href={risk.steam_url} target="_blank" rel="noreferrer" className="hover:underline">
              профиль Steam
            </a>
          ) : (
            "—"
          )}
        </Row>
        <Row label="Аккаунт у нас">{age(risk.account_created_at)}</Row>
        <Row label="Блокировка">
          {risk.banned ? (
            <span className={danger}>
              заблокирован{risk.ban_reason ? `: ${risk.ban_reason}` : ""}
            </span>
          ) : (
            "нет"
          )}
        </Row>
        <Row label="Кошелёк">
          {risk.wallet_frozen ? <span className={danger}>заморожен</span> : "активен"}
        </Row>
        <Row label="Выкуп">
          {risk.sell_blocked ? (
            <span className={danger}>
              запрещён{risk.sell_block_reason ? `: ${risk.sell_block_reason}` : ""}
            </span>
          ) : (
            "разрешён"
          )}
        </Row>
        <Row label="Продано всего">
          {risk.sold_count} · <Money uzs={risk.sold_uzs} />
        </Row>
        <Row label="Выплачено на карты">
          {risk.paid_count} · <Money uzs={risk.paid_uzs} />
        </Row>
        <Row label="На эту карту">
          <Money uzs={risk.card_paid_uzs} /> (все аккаунты)
        </Row>
        <Row label="Продаж за 24 ч">
          {risk.day_count} · <Money usd={risk.day_usd} />
        </Row>
        <Row label="Та же карта у других">
          {!risk.card_known ? (
            "неизвестно (карта старая, отпечаток ещё не посчитан)"
          ) : risk.shared_card_users.length === 0 ? (
            "нет"
          ) : (
            <ul className={danger}>
              {risk.shared_card_users.map((u) => (
                <li key={u.id}>
                  <UserCell id={u.id} name={u.display_name} avatarUrl={u.avatar_url} />
                </li>
              ))}
            </ul>
          )}
        </Row>
      </dl>
      <div className="mt-3">
        <SellBlockToggle detail={detail} risk={risk} />
      </div>
    </Section>
  );
}
