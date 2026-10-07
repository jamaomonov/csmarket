/** «Покупка LIS-SKINS»: a LIS-SKINS order's purchase — status, Steam offer, ids to search by. */
import { type ReactNode } from "react";

import { type AdminLisskinsPurchaseOut } from "./api";
import { ATTENTION_LABELS } from "./labels";

import { formatDateTime } from "@/lib/format";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="text-fg-muted w-40 shrink-0">{label}</dt>
      <dd className="min-w-0 break-all">{children}</dd>
    </div>
  );
}

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

interface LisskinsBlockProps {
  purchase: AdminLisskinsPurchaseOut;
}

export function LisskinsBlock({ purchase: p }: LisskinsBlockProps) {
  return (
    <section aria-label="Покупка LIS-SKINS" className="space-y-2">
      <h2 className="text-lg font-semibold">Покупка LIS-SKINS</h2>
      <dl className="space-y-1 text-sm">
        <Field label="Purchase id">{p.purchase_id ?? "—"}</Field>
        <Field label="custom_id">{p.custom_id}</Field>
        <Field label="Лот">{p.skin_id}</Field>
        <Field label="Статус">{p.status ?? "—"}</Field>
        <Field label="Предложение">
          {p.offer_url !== null && p.offer_id !== null ? (
            <a href={p.offer_url} target="_blank" rel="noreferrer" className="text-accent">
              {p.offer_id}
            </a>
          ) : (
            "—"
          )}
        </Field>
        {p.offer_expiry_at !== null && <Field label="Принять до">{when(p.offer_expiry_at)}</Field>}
        <Field label="Списано">{p.amount_usd === null ? "—" : `$${p.amount_usd}`}</Field>
        {p.return_reason !== null && (
          <Field label="Возврат">
            {p.error === null ? p.return_reason : `${p.return_reason} · ${p.error}`}
          </Field>
        )}
        {p.buy_pending && <Field label="Покупка">ждёт попытки</Field>}
        {p.buy_unconfirmed_at !== null && (
          <Field label="Ответ потерян">{when(p.buy_unconfirmed_at)}</Field>
        )}
        {p.attention_reason !== null && (
          <Field label="Внимание">
            {ATTENTION_LABELS[p.attention_reason]}
            {p.resolved_at !== null && ` · разобрано ${when(p.resolved_at)}`}
          </Field>
        )}
      </dl>
    </section>
  );
}
