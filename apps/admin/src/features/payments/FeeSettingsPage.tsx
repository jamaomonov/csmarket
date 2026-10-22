/**
 * «Настройки оплаты»: the percent each kassa adds on top of an order or a top-up paid through
 * it (spec 2026-10-14-kassa-fee). A save affects new payments only — an open one keeps the fee
 * it was shown; audited. The save names the version it was edited from, so a stale tab cannot
 * write old numbers back. One `SaveBar` saves the fees, the kassa states and «Лимит без
 * проверки» together; switching a kassa off asks first («Payme будет скрыт на сайте»).
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getFeeSettings, saveFeeSettings, type KassaFees, type KassaStatus } from "./api";
import { LIMITS_INVALID, ReviewLimitsBlock, useReviewLimits } from "./ReviewLimitsBlock";

import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { countChanges, SaveBar } from "@/components/SaveBar";
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
const RATE_INVALID = "Комиссия — число от 0 до 10, не больше двух знаков после точки.";

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

/** The states as the page shows them: a kassa missing from the document has its default. */
function normalised(doc: KassaFees): KassaFees {
  return {
    ...doc,
    statuses: Object.fromEntries(SWITCHED.map((k) => [k.slug, statusOf(doc, k.slug)])),
  };
}

/** The kassas this draft hides from the site that the saved document shows. */
function goingOff(saved: KassaFees, doc: KassaFees): string[] {
  return SWITCHED.filter(
    ({ slug }) => statusOf(saved, slug) !== "off" && statusOf(doc, slug) === "off",
  ).map(({ label }) => label);
}

function valid(doc: KassaFees): boolean {
  return KASSAS.every(({ key }) => RATE.test(doc[key]) && Number(doc[key]) <= 10);
}

export function FeeSettingsPage() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: KEY, queryFn: getFeeSettings });
  const limits = useReviewLimits();
  const [draft, setDraft] = useState<KassaFees | null>(null);
  const [invalid, setInvalid] = useState<string[]>([]);
  const [hiding, setHiding] = useState<string[] | null>(null);
  const key = useIdempotencyKey("admin-fee-settings");
  const version = settings.data?.updated_at ?? null;
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const save = useMutation({
    mutationFn: (doc: KassaFees) => saveFeeSettings(doc, version, key.keyFor(JSON.stringify(doc))),
    onSuccess: (out) => {
      key.reset();
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
  const saved = settings.data;
  const doc = draft ?? saved.settings;
  const feesChanged =
    draft === null ? 0 : countChanges(normalised(saved.settings), normalised(doc));
  const changed = feesChanged + limits.changed;
  const saving = save.isPending || limits.mutation.isPending;
  const run = async (): Promise<void> => {
    setHiding(null);
    try {
      if (feesChanged > 0) await save.mutateAsync(doc);
      if (limits.changed > 0) await limits.save();
      setSavedAt(new Date());
    } catch {
      // Shown in the save bar from the mutation's error.
    }
  };
  const submit = (): void => {
    const wrong = [
      ...(feesChanged > 0 && !valid(doc) ? [RATE_INVALID] : []),
      ...(limits.changed > 0 && !limits.valid() ? [LIMITS_INVALID] : []),
    ];
    setInvalid(wrong);
    if (wrong.length > 0) return;
    const off = goingOff(saved.settings, doc);
    if (off.length > 0) setHiding(off);
    else void run();
  };
  const failed = save.error ?? limits.mutation.error;
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
      <ReviewLimitsBlock limits={limits} />
      <SaveBar
        changed={changed}
        saving={saving}
        onSave={submit}
        onReset={() => {
          setDraft(null);
          setInvalid([]);
          save.reset();
          limits.reset();
        }}
      >
        {invalid.map((text) => (
          <p key={text} role="alert" className="text-danger text-sm">
            {text}
          </p>
        ))}
        {failed ? (
          <p role="alert" className="text-danger text-sm">
            {payoutErrorText(failed)}
          </p>
        ) : null}
      </SaveBar>
      {hiding !== null ? (
        <Modal
          title={`Выключить: ${hiding.join(", ")}?`}
          description="Начатые оплаты дойдут до конца."
          onClose={() => {
            setHiding(null);
          }}
        >
          <ul className="space-y-1 text-sm">
            {hiding.map((label) => (
              <li key={label}>{label} будет скрыт на сайте.</li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                setHiding(null);
              }}
            >
              Отмена
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                void run();
              }}
            >
              Да, выключить
            </Button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
