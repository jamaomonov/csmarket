/**
 * «Заявка на выплату»: the card (masked; «Показать номер» / «Скопировать номер» go through the
 * audited reveal, the number lives only in this page's state), the money, the items, the
 * seller's history, and «Выплачено» / «Отклонить» behind a confirm, one key per submission.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getPayout, markPaid, type PayoutDetail as Detail, rejectPayout, revealCard } from "./api";
import { PAYOUTS_KEY, payoutKey } from "./keys";
import { cardLabel, groupDigits, PAYOUT_LABELS, payoutErrorText, SALE_LABELS } from "./labels";

import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime, formatSum } from "@/lib/format";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="text-fg-muted w-44 shrink-0">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function CardBlock({ detail }: { detail: Detail }) {
  const [number, setNumber] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const show = useMutation({
    mutationFn: () => revealCard(detail.request.id, "show"),
    onSuccess: (r) => {
      setNumber(r.number);
    },
  });
  const copy = useMutation({
    mutationFn: async () => {
      const r = await revealCard(detail.request.id, "copy");
      await navigator.clipboard.writeText(r.number);
    },
    onSuccess: () => {
      setCopied(true);
    },
  });
  return (
    <section className="border-border flex flex-col gap-2 rounded-lg border p-4">
      <h2 className="font-semibold">Карта</h2>
      <p className="font-mono text-lg">
        {cardLabel(detail.request.card_type, detail.request.card_masked)}
      </p>
      {number !== null ? (
        <p className="font-mono text-lg tracking-wider">{groupDigits(number)}</p>
      ) : null}
      <div className="flex gap-2">
        <Button
          variant="secondary"
          disabled={show.isPending}
          onClick={() => {
            show.mutate();
          }}
        >
          Показать номер
        </Button>
        <Button
          variant="secondary"
          disabled={copy.isPending}
          onClick={() => {
            copy.mutate();
          }}
        >
          Скопировать номер
        </Button>
        {copied ? <span className="text-fg-muted self-center text-sm">Скопировано</span> : null}
      </div>
      {show.isError || copy.isError ? (
        <p role="alert" className="text-danger text-sm">
          {errorText(show.error ?? copy.error)}
        </p>
      ) : null}
    </section>
  );
}

type Panel = "none" | "paid" | "reject";

function Actions({ detail, onStale }: { detail: Detail; onStale: () => void }) {
  const qc = useQueryClient();
  const id = detail.request.id;
  const [panel, setPanel] = useState<Panel>("none");
  const [text, setText] = useState("");
  const paidKey = useIdempotencyKey("admin-payout-paid");
  const rejectKey = useIdempotencyKey("admin-payout-reject");
  const act = useMutation({
    mutationFn: (p: Exclude<Panel, "none">): Promise<Detail> => {
      const value = text.trim();
      return p === "paid"
        ? markPaid(id, value || null, paidKey.keyFor(JSON.stringify({ id, value })))
        : rejectPayout(id, value, rejectKey.keyFor(JSON.stringify({ id, value })));
    },
    onSuccess: (next, p) => {
      (p === "paid" ? paidKey : rejectKey).reset();
      qc.setQueryData(payoutKey(id), next);
      void qc.invalidateQueries({ queryKey: PAYOUTS_KEY });
      setPanel("none");
      setText("");
    },
    onError: () => {
      onStale();
    },
  });
  if (!detail.can_decide) return null;
  return (
    <section className="flex flex-col gap-3">
      <div className="flex gap-2">
        <Button
          onClick={() => {
            setPanel("paid");
          }}
        >
          Выплачено
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            setPanel("reject");
          }}
        >
          Отклонить
        </Button>
      </div>
      {panel !== "none" ? (
        <div
          role="group"
          aria-label="Подтверждение"
          className="border-border bg-surface flex flex-col gap-3 rounded-lg border p-4"
        >
          <label className="flex flex-col gap-1 text-sm">
            {panel === "paid" ? "Комментарий" : "Причина"}
            <textarea
              maxLength={500}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
              }}
              className="border-border bg-bg rounded-md border p-2"
            />
          </label>
          {panel === "reject" ? (
            <p className="text-fg-muted text-sm">
              {formatSum(Number(detail.request.amount_uzs) + Number(detail.request.fee_uzs))} будут
              зачислены на баланс пользователя.
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button
              disabled={act.isPending || (panel === "reject" && text.trim() === "")}
              onClick={() => {
                act.mutate(panel);
              }}
            >
              {panel === "paid" ? "Да, выплачено" : "Да, отклонить"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setPanel("none");
              }}
            >
              Отмена
            </Button>
          </div>
          {act.isError ? (
            <p role="alert" className="text-danger text-sm">
              {payoutErrorText(act.error)}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function PayoutDetail() {
  const { id = "" } = useParams();
  const detail = useQuery({ queryKey: payoutKey(id), queryFn: () => getPayout(id) });
  if (detail.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(detail.error)}
      </p>
    );
  }
  if (!detail.data) return <p className="text-fg-muted">Загрузка…</p>;
  const d = detail.data;
  const s = d.sale;
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold">
          Выплата по продаже{" "}
          <Link to={`/sales/${s.number}`} className="font-mono hover:underline">
            {s.number}
          </Link>
        </h1>
        <p className="text-fg-muted">
          {PAYOUT_LABELS[d.request.status]} · {d.request.user.display_name ?? "Без имени"}
        </p>
      </header>
      <CardBlock detail={d} />
      <dl className="flex flex-col gap-1 text-sm">
        <Field label="Предметы">{formatSum(s.items_uzs)}</Field>
        <Field label="Комиссия карты">−{formatSum(s.fee_uzs)}</Field>
        <Field label="К выплате">{formatSum(d.request.amount_uzs)}</Field>
        <Field label="Skinslink платит нам">${s.amount_usd ?? s.quoted_usd}</Field>
        <Field label="Наша маржа">${s.margin_usd}</Field>
        <Field label="К выплате с">
          {d.request.to_pay_at ? formatDateTime(d.request.to_pay_at) : "—"}
        </Field>
        {d.note ? <Field label="Комментарий">{d.note}</Field> : null}
        {d.reject_reason ? <Field label="Причина отказа">{d.reject_reason}</Field> : null}
      </dl>
      <Actions detail={d} onStale={() => void detail.refetch()} />
      <section>
        <h2 className="mb-2 font-semibold">Предметы</h2>
        <ul className="text-sm">
          {s.items.map((i) => (
            <li key={i.asset_id} className="border-border flex justify-between border-t py-1.5">
              <span>{i.name}</span>
              <span className="tabular-nums">
                ${i.price_usd} · {formatSum(i.price_uzs)}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="mb-2 font-semibold">История пользователя</h2>
        <ul className="text-sm">
          {d.history_sales.map((h) => (
            <li key={h.number} className="border-border flex justify-between border-t py-1.5">
              <Link to={`/sales/${h.number}`} className="font-mono hover:underline">
                {h.number}
              </Link>
              <span>{SALE_LABELS[h.status]}</span>
              <span className="tabular-nums">{formatSum(h.payout_uzs)}</span>
            </li>
          ))}
          {d.history_payouts.map((h) => (
            <li key={h.id} className="border-border flex justify-between border-t py-1.5">
              <Link to={`/payouts/${h.id}`} className="font-mono hover:underline">
                {h.sale_number}
              </Link>
              <span>{PAYOUT_LABELS[h.status]}</span>
              <span className="tabular-nums">{formatSum(h.amount_uzs)}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
