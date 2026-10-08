/** «Продажа»: statuses, Skinslink's amount, our payout and margin, the items, the payout. */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getSale } from "./api";
import { saleKey } from "./keys";
import { ATTENTION_LABELS, cardLabel, PAYOUT_LABELS, SALE_LABELS } from "./labels";
import { Field, ItemList } from "./Parts";

import { errorText } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";

const at = (iso: string | null): string => (iso ? formatDateTime(iso) : "—");

export function SaleDetail() {
  const { number = "" } = useParams();
  const sale = useQuery({ queryKey: saleKey(number), queryFn: () => getSale(number) });
  if (sale.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(sale.error)}
      </p>
    );
  }
  if (!sale.data) return <p className="text-fg-muted">Загрузка…</p>;
  const s = sale.data;
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <h1 className="font-mono text-2xl font-bold">{s.number}</h1>
      {s.attention_reason ? (
        <p role="alert" className="text-danger">
          {ATTENTION_LABELS[s.attention_reason] ?? s.attention_reason}
        </p>
      ) : null}
      <dl className="flex flex-col gap-1 text-sm">
        <Field label="Статус">{SALE_LABELS[s.status]}</Field>
        <Field label="Пользователь">
          <Link to={`/users/${s.user.id}`} className="hover:underline">
            {s.user.display_name ?? "Без имени"}
          </Link>
        </Field>
        <Field label="Куда">
          {s.payout_to === "card" ? cardLabel(s.card_type, s.card_masked) : "баланс"}
        </Field>
        <Field label="Skinslink: котировка">${s.quoted_usd}</Field>
        <Field label="Skinslink: зачисляет">
          {s.amount_usd !== null ? `$${s.amount_usd}` : "—"}
        </Field>
        <Field label="Курс">{s.rate}</Field>
        <Field label="Предметы">{formatSum(s.items_uzs)}</Field>
        {s.payout_to === "card" ? (
          <Field label="Комиссия карты">−{formatSum(s.fee_uzs)}</Field>
        ) : (
          <Field label="Бонус за баланс">+{formatSum(s.bonus_uzs)}</Field>
        )}
        <Field label="Выплата">{formatSum(s.payout_uzs)}</Field>
        <Field label="Наша маржа">${s.margin_usd}</Field>
        <Field label="Обмен Skinslink">{s.trade_id ?? "—"}</Field>
        <Field label="Оффер Steam">{s.trade_offer_id ?? "—"}</Field>
        <Field label="Бот">{s.bot_name ?? "—"}</Field>
        <Field label="Холд до">{at(s.hold_end_at)}</Field>
        <Field label="Причина закрытия">{s.fail_reason ?? "—"}</Field>
        <Field label="Зачислено">{at(s.credited_at)}</Field>
        <Field label="Создана">{at(s.created_at)}</Field>
        {s.payout ? (
          <Field label="Выплата на карту">
            <Link to={`/payouts/${s.payout.id}`} className="hover:underline">
              {PAYOUT_LABELS[s.payout.status]}
            </Link>
          </Field>
        ) : null}
      </dl>
      <ItemList items={s.items} />
    </div>
  );
}
