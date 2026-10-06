/** «Покупка Skinslink»: a Skinslink order's purchase — status, Steam offer, ids to search by. */
import { type ReactNode } from "react";

import { type AdminSkinslinkPurchaseOut } from "./api";
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

interface SkinslinkBlockProps {
  purchase: AdminSkinslinkPurchaseOut;
}

export function SkinslinkBlock({ purchase: p }: SkinslinkBlockProps) {
  return (
    <section aria-label="Покупка Skinslink" className="space-y-2">
      <h2 className="text-lg font-semibold">Покупка Skinslink</h2>
      <dl className="space-y-1 text-sm">
        <Field label="Purchase id">{p.purchase_id ?? "—"}</Field>
        <Field label="merchant_tx_id">{p.merchant_tx_id}</Field>
        <Field label="Asset id">{p.asset_id}</Field>
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
        <Field label="Списано">{p.amount_usd === null ? "—" : `$${p.amount_usd}`}</Field>
        {p.fail_reason !== null && <Field label="Причина">{p.fail_reason}</Field>}
        {p.hold_end_date !== null && <Field label="Холд до">{when(p.hold_end_date)}</Field>}
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
