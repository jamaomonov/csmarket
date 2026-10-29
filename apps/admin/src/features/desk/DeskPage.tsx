/**
 * «Мои сделки»: the owner's own figures for a period, «Вывел себе», and the deals list.
 * Kept apart from the shop's numbers (spec 2026-10-29-desk).
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, type SubmitEvent, useState } from "react";
import { Link } from "react-router-dom";

import { addWithdrawal, DESK_KEY, getSummary, listDeals } from "./api";
import { DEAL_STATUS, deskErrorText, METHOD } from "./labels";

import { Money } from "@/components/Money";
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
  return (
    <section className="space-y-4">
      <PageHeader
        title="Мои сделки"
        meta="Личные сделки с трейдерами — отдельно от цифр магазина."
        actions={
          <div className="flex gap-2">
            <Link to="/desk/stock">
              <Button variant="secondary">Склад</Button>
            </Link>
            <Link to="/desk/new">
              <Button>Новая сделка</Button>
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
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5" aria-label="Итоги">
          <Tile title="Прибыль">
            <Money usd={s.profit_usd} signed />
          </Tile>
          <Tile title="Выручка Skinslink">
            <Money usd={s.revenue_usd} />
          </Tile>
          <Tile title="В пути">
            <Money usd={s.in_transit_usd} />
          </Tile>
          <Tile title="На складе">
            <Money usd={s.stock_usd} />
          </Tile>
          <Tile title="Моя доля на Skinslink">
            <Money usd={s.skinslink_share_usd} />
            <Withdraw />
          </Tile>
        </div>
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
      {deals.data?.items.length === 0 && (
        <p className="text-fg-muted">Сделок пока нет. Начните с «Новая сделка».</p>
      )}
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
              <span className="w-24 text-right text-sm" title={d.resolved ? "итог" : "пока"}>
                <Money usd={d.profit_usd} signed />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Tile({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-border bg-surface rounded-lg border p-3">
      <p className="text-fg-muted text-xs">{title}</p>
      <div className="mt-1 font-semibold">{children}</div>
    </div>
  );
}

/** «Вывел себе»: an amount in dollars and a note; the share drops by it. */
function Withdraw() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => addWithdrawal(amount.trim(), note.trim() || undefined),
    onSuccess: () => {
      setOpen(false);
      setAmount("");
      setNote("");
      void qc.invalidateQueries({ queryKey: DESK_KEY });
    },
  });
  if (!open) {
    return (
      <button
        type="button"
        className="text-accent mt-1 block text-xs font-normal underline"
        onClick={() => {
          setOpen(true);
        }}
      >
        Вывел себе
      </button>
    );
  }
  const submit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (Number(amount) > 0) save.mutate();
  };
  return (
    <form className="mt-2 flex flex-col gap-2 text-sm font-normal" onSubmit={submit}>
      <input
        aria-label="Сколько вывел, $"
        inputMode="decimal"
        value={amount}
        onChange={(e) => {
          setAmount(e.target.value.replace(",", "."));
        }}
        placeholder="$"
        className="border-border bg-bg h-10 rounded-md border px-2"
      />
      <input
        aria-label="Заметка"
        value={note}
        onChange={(e) => {
          setNote(e.target.value);
        }}
        placeholder="куда"
        className="border-border bg-bg h-10 rounded-md border px-2"
      />
      {save.isError && <p className="text-danger text-xs">{deskErrorText(save.error)}</p>}
      <Button type="submit" size="sm" disabled={save.isPending || !(Number(amount) > 0)}>
        Записать
      </Button>
    </form>
  );
}
