/** «Обмен»: the order's Waxpeer trade — status, Steam offer, deadlines, seller, ids to copy. */
import { type ReactNode, useState } from "react";

import { type AdminTradeOut } from "./api";
import { ATTENTION_LABELS, waxpeerStatusLabel } from "./labels";

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

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    // A blocked clipboard (insecure context, denied permission) just leaves the button idle.
    navigator.clipboard.writeText(value).then(
      () => {
        setCopied(true);
      },
      () => {
        setCopied(false);
      },
    );
  };
  return (
    <button
      type="button"
      aria-label={label}
      onClick={copy}
      className="text-accent ml-2 text-xs hover:underline"
    >
      {copied ? "Скопировано" : "Копировать"}
    </button>
  );
}

/** The seller's public name and level, when the stored object has them as scalars. */
function sellerText(seller: Record<string, unknown>): string {
  const name = typeof seller.name === "string" ? seller.name : null;
  const level = typeof seller.level === "number" ? ` (уровень ${String(seller.level)})` : "";
  return name === null ? "—" : `${name}${level}`;
}

function penaltiesText(penalties: unknown): string {
  if (penalties === null || penalties === undefined) return "нет";
  if (typeof penalties === "object" && Object.keys(penalties).length === 0) return "нет";
  return typeof penalties === "string" ? penalties : JSON.stringify(penalties);
}

function Attention({ trade }: { trade: AdminTradeOut }) {
  if (trade.attention_reason === null) return null;
  return (
    <Field label="Внимание">
      {ATTENTION_LABELS[trade.attention_reason]}
      {trade.resolved_at !== null && (
        <span className="text-fg-muted">
          {" "}
          · разобрано {formatDateTime(trade.resolved_at)}
          {trade.resolved_note !== null && `: ${trade.resolved_note}`}
        </span>
      )}
    </Field>
  );
}

export function TradeBlock({ trade }: { trade: AdminTradeOut | null }) {
  return (
    <section aria-label="Обмен" className="space-y-2">
      <h2 className="text-lg font-semibold">Обмен</h2>
      {trade === null ? (
        <p className="text-fg-muted text-sm">Покупки в Waxpeer ещё не было.</p>
      ) : (
        <dl className="space-y-1 text-sm">
          <Field label="Статус Waxpeer">{waxpeerStatusLabel(trade.status)}</Field>
          <Field label="Обмен в Steam">
            {trade.trade_id === null ? (
              "—"
            ) : trade.offer_url === null ? (
              trade.trade_id
            ) : (
              <a
                href={trade.offer_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                {trade.trade_id}
              </a>
            )}
          </Field>
          <Field label="Отправить до">{when(trade.send_until)}</Field>
          <Field label="Принят">{when(trade.accepted_at)}</Field>
          <Field label="Защита до">
            {when(trade.release_date)}
            {trade.is_released && <span className="text-fg-muted"> · снята</span>}
          </Field>
          <Field label="Продавец">{sellerText(trade.seller)}</Field>
          <Field label="Причина">{trade.reason ?? "—"}</Field>
          <Field label="Штрафы">{penaltiesText(trade.penalties)}</Field>
          <Attention trade={trade} />
          <Field label="Project id">
            <span className="font-mono">{trade.project_id}</span>
            <CopyButton value={trade.project_id} label="Скопировать project id" />
          </Field>
          <Field label="Id Waxpeer">
            {trade.waxpeer_id === null ? (
              "—"
            ) : (
              <>
                <span className="font-mono">{String(trade.waxpeer_id)}</span>
                <CopyButton value={String(trade.waxpeer_id)} label="Скопировать id Waxpeer" />
              </>
            )}
          </Field>
        </dl>
      )}
    </section>
  );
}
