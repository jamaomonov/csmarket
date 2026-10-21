/**
 * «Настройки оплаты»: the percent each kassa adds on top of an order or a top-up paid through
 * it (spec 2026-10-14-kassa-fee). A save affects new payments only — an open one keeps the fee
 * it was shown; audited. The save names the version it was edited from, so a stale tab cannot
 * write old numbers back.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getFeeSettings, saveFeeSettings, type KassaFees, type KassaStatus } from "./api";
import { ReviewLimitsBlock } from "./ReviewLimitsBlock";

import { PageHeader } from "@/components/PageHeader";
import { SavedNotice } from "@/components/SavedNotice";
import { Tabs } from "@/components/Tabs";
import { payoutErrorText } from "@/features/sales/labels";
import { NumberField } from "@/features/sales/SettingsParts";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

const KEY = ["admin", "payments", "settings"] as const;
type RateKey = Exclude<keyof KassaFees, "statuses">;

const KASSAS: readonly { key: RateKey; label: string }[] = [
  { key: "click", label: "Комиссия Click, %" },
  { key: "payme", label: "Комиссия Payme, %" },
  { key: "uzum", label: "Комиссия Uzum, %" },
];
const RATE = /^\d{1,2}(\.\d{1,2})?$/;

/** Every kassa with a switch (P2P has no fee: a card transfer costs the buyer nothing). */
const SWITCHED: readonly { slug: string; label: string }[] = [
  { slug: "click", label: "Click" },
  { slug: "payme", label: "Payme" },
  { slug: "uzum", label: "Uzum" },
  { slug: "p2p", label: "Перевод на карту (P2P)" },
];
const STATUS_ITEMS: { key: KassaStatus; label: string }[] = [
  { key: "on", label: "Работает" },
  { key: "maintenance", label: "Тех. работы" },
  { key: "off", label: "Выключен" },
];

function statusOf(doc: KassaFees, slug: string): KassaStatus {
  return doc.statuses[slug] ?? (slug === "p2p" ? "off" : "on");
}

function valid(doc: KassaFees): boolean {
  return KASSAS.every(({ key }) => RATE.test(doc[key]) && Number(doc[key]) <= 10);
}

export function FeeSettingsPage() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: KEY, queryFn: getFeeSettings });
  const [draft, setDraft] = useState<KassaFees | null>(null);
  const [invalid, setInvalid] = useState(false);
  const key = useIdempotencyKey("admin-fee-settings");
  const version = settings.data?.updated_at ?? null;
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const save = useMutation({
    mutationFn: (doc: KassaFees) => saveFeeSettings(doc, version, key.keyFor(JSON.stringify(doc))),
    onSuccess: (out) => {
      key.reset();
      setSavedAt(new Date());
      qc.setQueryData(KEY, out);
      setDraft(null);
    },
  });
  if (settings.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(settings.error)}
      </p>
    );
  }
  if (!settings.data) return <p className="text-fg-muted">Загрузка…</p>;
  const doc = draft ?? settings.data.settings;
  const saved = settings.data;
  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <PageHeader
        title="Настройки оплаты"
        meta={
          saved.updated_at
            ? `сохранено ${formatDateTime(saved.updated_at)}${
                saved.updated_by?.display_name ? ` · ${saved.updated_by.display_name}` : ""
              }`
            : "ещё не сохраняли"
        }
      />
      <SavedNotice at={savedAt} />
      <section className="border-border bg-surface flex flex-col gap-3 rounded-lg border p-4">
        <p className="text-fg-muted text-sm">
          Добавляется к сумме оплаты через эту кассу: и заказа, и пополнения. 0 — без комиссии.
          Открытые платежи сохраняют прежнюю комиссию.
        </p>
        <div className="flex flex-wrap gap-4">
          {KASSAS.map(({ key: k, label }) => (
            <NumberField
              key={k}
              label={label}
              value={doc[k]}
              onChange={(v) => {
                setDraft({ ...doc, [k]: v });
              }}
            />
          ))}
        </div>
      </section>
      <section className="border-border bg-surface flex flex-col gap-3 rounded-lg border p-4">
        <h2 className="font-semibold">Состояние касс</h2>
        <p className="text-fg-muted text-sm">
          «Тех. работы» — касса видна на сайте, но не нажимается. «Выключен» — её не видно. Начатые
          оплаты в обоих случаях доходят до конца.
        </p>
        <div className="flex flex-col gap-3">
          {SWITCHED.map(({ slug, label }) => (
            <div key={slug} className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium">{label}</span>
              <Tabs<KassaStatus>
                label={`${label}: состояние`}
                variant="segmented"
                value={statusOf(doc, slug)}
                onChange={(next) => {
                  setDraft({ ...doc, statuses: { ...doc.statuses, [slug]: next } });
                }}
                items={STATUS_ITEMS}
              />
            </div>
          ))}
        </div>
      </section>
      <ReviewLimitsBlock />
      {invalid && (
        <p role="alert" className="text-danger text-sm">
          Комиссия — число от 0 до 10, не больше двух знаков после точки.
        </p>
      )}
      {save.isError && (
        <p role="alert" className="text-danger text-sm">
          {payoutErrorText(save.error)}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          type="button"
          disabled={draft === null || save.isPending}
          onClick={() => {
            if (!valid(doc)) {
              setInvalid(true);
              return;
            }
            setInvalid(false);
            save.mutate(doc);
          }}
        >
          Сохранить
        </Button>
        {draft !== null && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setDraft(null);
              setInvalid(false);
            }}
          >
            Отменить
          </Button>
        )}
      </div>
    </div>
  );
}
