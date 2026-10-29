/**
 * «Мои сделки»: the owner's own figures for a period, «Вывел себе», and the deals list.
 * Kept apart from the shop's numbers (spec 2026-10-29-desk).
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { addWithdrawal, DESK_KEY, getSummary, listDeals } from "./api";
import { DEAL_STATUS, deskErrorText, METHOD } from "./labels";
import { TAP } from "./Parts";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { EmptyState } from "@/components/EmptyState";
import { Money } from "@/components/Money";
import { MoneyField } from "@/components/MoneyInput";
import { PageHeader } from "@/components/PageHeader";
import { StatusChip } from "@/components/StatusChip";
import { Tabs } from "@/components/Tabs";
import { When } from "@/components/When";

const PERIODS = { "1": "Сегодня", "7": "7 дней", "30": "30 дней", "365": "Год" } as const;
type Period = keyof typeof PERIODS;

/** `YYYY-MM-DD` of `days − 1` days ago, in the browser's day (the owner is in Tashkent). */
function since(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - (days - 1));
  return d.toLocaleDateString("sv-SE");
}

export function DeskPage() {
  const [period, setPeriod] = useState<Period>("30");
  const [q, setQ] = useState("");
  const summary = useQuery({
    queryKey: [...DESK_KEY, "summary", period],
    queryFn: () => getSummary(since(Number(period))),
  });
  const deals = useQuery({
    queryKey: [...DESK_KEY, "deals", q.trim()],
    queryFn: () => listDeals(q.trim() ? { q: q.trim() } : {}),
  });
  const s = summary.data;
  const [withdrawing, setWithdrawing] = useState(false);
  return (
    <section className="space-y-4">
      <PageHeader
        title="Мои сделки"
        meta="Личные сделки с трейдерами — отдельно от цифр магазина."
        actions={
          <div className="flex gap-2">
            <Link to="/desk/stock">
              <Button variant="secondary" className={TAP}>
                Склад
              </Button>
            </Link>
            <Link to="/desk/new">
              <Button className={TAP}>Новая сделка</Button>
            </Link>
          </div>
        }
      />
      <Tabs
        label="Период"
        value={period}
        onChange={setPeriod}
        items={(Object.keys(PERIODS) as Period[]).map((k) => ({ key: k, label: PERIODS[k] }))}
      />
      {summary.isError && (
        <p role="alert" className="text-danger">
          {deskErrorText(summary.error)}
        </p>
      )}
      {s && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5" aria-label="Итоги">
          <Tile title="Прибыль">
            <Money usd={s.profit_usd} signed />
          </Tile>
          <Tile title="Выручка Skinslink">
            <Money usd={s.revenue_usd} />
          </Tile>
          <Tile
            title="Оплачено, не продано"
            hint="Деньги в скинах, которые ещё не зачислены Skinslink"
          >
            <Money usd={s.in_transit_usd} />
          </Tile>
          <Tile title="На складе" hint="Скины «Себе» по цене покупки">
            <Money usd={s.stock_usd} />
          </Tile>
          <Tile title="Мои деньги на Skinslink" hint="Зачислено по сделкам минус выведенное" wide>
            <Money usd={s.skinslink_share_usd} />
            <Button
              variant="secondary"
              className={`mt-2 w-full ${TAP}`}
              onClick={() => {
                setWithdrawing(true);
              }}
            >
              Вывод себе
            </Button>
          </Tile>
        </div>
      )}
      {withdrawing && (
        <Withdraw
          onClose={() => {
            setWithdrawing(false);
          }}
        />
      )}
      <label className="flex max-w-sm flex-col gap-1 text-sm">
        Трейдер
        <input
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
          }}
          placeholder="Имя или ник"
          className="border-border bg-bg h-11 rounded-md border px-3"
        />
      </label>
      {deals.isPending && <p className="text-fg-muted">Загружаем…</p>}
      {deals.data?.items.length === 0 &&
        (q.trim() ? (
          <p className="text-fg-muted">Ничего не нашли по «{q.trim()}».</p>
        ) : (
          <EmptyState
            action={
              <Link to="/desk/new">
                <Button className={TAP}>Новая сделка</Button>
              </Link>
            }
          >
            Сделок пока нет
          </EmptyState>
        ))}
      <ul className="divide-border border-border divide-y rounded-lg border" aria-label="Сделки">
        {deals.data?.items.map((d) => (
          <li key={d.id}>
            <Link
              to={`/desk/deals/${d.id}`}
              className="hover:bg-surface-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-3"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{d.trader}</span>
                <span className="text-fg-muted text-xs">
                  <When iso={d.created_at} /> · {METHOD[d.method]} · {d.items} шт.
                </span>
              </span>
              <span className="text-sm">
                {d.paid_amount && d.paid_currency === "UZS" ? (
                  <Money uzs={d.paid_amount} />
                ) : d.paid_usd ? (
                  <Money usd={d.paid_usd} />
                ) : (
                  <span className="text-fg-muted">без цены</span>
                )}
              </span>
              <StatusChip tone={DEAL_STATUS[d.status].tone}>
                {DEAL_STATUS[d.status].label}
              </StatusChip>
              <span className="w-24 text-right text-sm">
                <Money usd={d.profit_usd} signed />
                {!d.resolved && <span className="text-fg-muted block text-xs">пока</span>}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface TileProps {
  title: string;
  hint?: string;
  wide?: boolean;
  children: ReactNode;
}

function Tile({ title, hint, wide = false, children }: TileProps) {
  return (
    <div
      className={`border-border bg-surface rounded-lg border p-3 ${wide ? "col-span-2 md:col-span-1" : ""}`}
    >
      <p className="text-fg-muted text-xs">{title}</p>
      <div className="mt-1 font-semibold">{children}</div>
      {hint && <p className="text-fg-dim mt-1 text-xs">{hint}</p>}
    </div>
  );
}

/** «Вывод себе»: an amount in dollars and a note; «Мои деньги на Skinslink» drop by it. */
function Withdraw({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => addWithdrawal(amount, note.trim() || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DESK_KEY });
      onClose();
    },
  });
  return (
    <ConfirmSheet title="Вывод себе" busy={save.isPending} onClose={onClose}>
      <MoneyField label="Сколько выведено" unit="$" decimal value={amount} onChange={setAmount} />
      <label className="flex flex-col gap-1 text-sm">
        Заметка
        <input
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          placeholder="Куда, например на карту"
          className="border-border bg-bg h-11 rounded-md border px-3"
        />
      </label>
      {save.isError && (
        <p role="alert" className="text-danger text-sm">
          {deskErrorText(save.error)}
        </p>
      )}
      <div className={CONFIRM_BUTTONS}>
        <Button variant="secondary" className={TAP} disabled={save.isPending} onClick={onClose}>
          Отмена
        </Button>
        <Button
          className={TAP}
          disabled={save.isPending || !(Number(amount) > 0)}
          onClick={() => {
            save.mutate();
          }}
        >
          Записать
        </Button>
      </div>
    </ConfirmSheet>
  );
}
