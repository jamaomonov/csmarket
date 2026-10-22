/**
 * «Настройки выкупа»: the sale-settings document. A save affects new sales only; audited. The
 * save names the version it was edited from: a tab left open while someone else saved gets
 * «уже сохранил кто-то другой» instead of silently writing old numbers back. `warnings` from
 * the API (a balance bonus that eats the margin) show above the form. The bottom `SaveBar` shows
 * only when something changed; turning «Выкуп включён» off asks «Выключить выкуп?».
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { CARD_TYPES_ORDER, getSaleSettings, saveSaleSettings, type SaleSettings } from "./api";
import { SALE_SETTINGS_KEY } from "./keys";
import { CARD_BRANDS, payoutErrorText } from "./labels";
import { LimitsSection, NumberField, WARNING_TEXT, withLimits } from "./SettingsParts";

import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { countChanges, SaveBar } from "@/components/SaveBar";
import { SavedNotice } from "@/components/SavedNotice";
import { Banner } from "@/components/Section";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

export function SaleSettingsPage() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: SALE_SETTINGS_KEY, queryFn: getSaleSettings });
  const [draft, setDraft] = useState<SaleSettings | null>(null);
  const [confirming, setConfirming] = useState(false);
  // The minimum is kept as typed, so an emptied field is not silently turned into 0.
  const [minText, setMinText] = useState<string | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);
  // Stable keys for the margin rows; null = one per row of the loaded document.
  const [rowIds, setRowIds] = useState<number[] | null>(null);
  const nextId = useRef(1000);
  const discard = () => {
    setDraft(null);
    setMinText(null);
    setRowIds(null);
    setInvalid(null);
  };
  const key = useIdempotencyKey("admin-sale-settings");
  const version = settings.data?.updated_at ?? null;
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const save = useMutation({
    mutationFn: (doc: SaleSettings) =>
      saveSaleSettings(doc, version, key.keyFor(JSON.stringify(doc))),
    onSuccess: (out) => {
      key.reset();
      setSavedAt(new Date());
      qc.setQueryData(SALE_SETTINGS_KEY, out);
      discard();
      setConfirming(false);
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
  const ids = rowIds ?? doc.margin.map((_, i) => i);
  const submit = () => {
    const min = (minText ?? String(doc.card_min_uzs)).trim();
    if (!/^\d+$/.test(min)) {
      setInvalid("Минимум на карту: целое число сум.");
      return;
    }
    setInvalid(null);
    save.mutate(withLimits({ ...doc, card_min_uzs: Number(min) }));
  };
  const savedDoc = settings.data.settings;
  const changed =
    draft === null && minText === null
      ? 0
      : countChanges(
          { ...withLimits(savedDoc), card_min_uzs: String(savedDoc.card_min_uzs) },
          { ...withLimits(doc), card_min_uzs: minText ?? String(doc.card_min_uzs) },
        );
  const turningOff = savedDoc.enabled && !doc.enabled;
  const set = (patch: Partial<SaleSettings>) => {
    setDraft({ ...doc, ...patch });
  };
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <PageHeader
        title="Настройки выкупа"
        meta={
          <>
            Курс ЦБ сейчас: {settings.data.rate_uzs ?? "нет"} · сохранено{" "}
            {settings.data.updated_at ? formatDateTime(settings.data.updated_at) : "никогда"}
            {settings.data.updated_by
              ? `, ${settings.data.updated_by.display_name ?? "без имени"}`
              : ""}
            . Новые настройки действуют на новые продажи.
          </>
        }
      />
      <SavedNotice at={savedAt} />
      {(settings.data.warnings ?? []).map((w) => (
        <Banner key={w}>{WARNING_TEXT[w]}</Banner>
      ))}
      <label
        className={`flex cursor-pointer items-center justify-between gap-4 rounded-lg border px-4 py-3 ${
          doc.enabled ? "border-success/40 bg-success/10" : "border-border bg-surface"
        }`}
      >
        <span>
          <span className="block font-semibold">Выкуп включён</span>
          <span className="text-fg-muted text-sm">
            {doc.enabled ? "Пользователи могут продавать скины." : "Продажа скинов выключена."}
          </span>
        </span>
        <input
          type="checkbox"
          role="switch"
          aria-label="Выкуп включён"
          checked={doc.enabled}
          onChange={(e) => {
            set({ enabled: e.target.checked });
          }}
          className="accent-success size-5"
        />
      </label>
      <section className="border-border bg-surface flex flex-col gap-2 rounded-lg border p-4">
        <h2 className="font-semibold">Маржа по диапазонам цены Skinslink</h2>
        <div aria-hidden className="text-fg-muted flex gap-2 text-xs">
          <span className="w-40">От, $</span>
          <span className="w-40">Маржа, %</span>
        </div>
        {doc.margin.map((b, i) => (
          <div key={ids[i]} className="flex flex-wrap items-end gap-2">
            <NumberField
              label={`От, $ (${String(i + 1)})`}
              value={b.from_usd}
              onChange={(v) => {
                set({ margin: doc.margin.map((x, j) => (j === i ? { ...x, from_usd: v } : x)) });
              }}
            />
            <NumberField
              label={`Маржа, % (${String(i + 1)})`}
              value={b.percent}
              onChange={(v) => {
                set({ margin: doc.margin.map((x, j) => (j === i ? { ...x, percent: v } : x)) });
              }}
            />
            <Button
              variant="secondary"
              aria-label="Убрать диапазон"
              disabled={doc.margin.length === 1}
              onClick={() => {
                set({ margin: doc.margin.filter((_, j) => j !== i) });
                setRowIds(ids.filter((_, j) => j !== i));
              }}
            >
              ×
            </Button>
          </div>
        ))}
        <Button
          variant="secondary"
          className="self-start"
          onClick={() => {
            set({ margin: [...doc.margin, { from_usd: "", percent: "" }] });
            setRowIds([...ids, nextId.current++]);
          }}
        >
          Добавить диапазон
        </Button>
      </section>
      <section className="border-border bg-surface flex flex-wrap gap-4 rounded-lg border p-4">
        <NumberField
          label="Скидка с курса ЦБ, %"
          value={doc.rate_cut_pct}
          onChange={(v) => {
            set({ rate_cut_pct: v });
          }}
        />
        <NumberField
          label="Бонус за баланс, %"
          value={doc.balance_bonus_pct}
          onChange={(v) => {
            set({ balance_bonus_pct: v });
          }}
        />
        {CARD_TYPES_ORDER.map((t) => (
          <NumberField
            key={t}
            label={`Комиссия ${CARD_BRANDS[t]}, %`}
            value={doc.card_fee_pct[t]}
            onChange={(v) => {
              set({ card_fee_pct: { ...doc.card_fee_pct, [t]: v } });
            }}
          />
        ))}
        <NumberField
          label="Комиссия банка, %"
          value={doc.bank_fee_pct ?? "1"}
          onChange={(v) => {
            set({ bank_fee_pct: v });
          }}
        />
        <NumberField
          label="Минимум на карту, сум"
          value={minText ?? String(doc.card_min_uzs)}
          onChange={(v) => {
            setMinText(v);
            if (draft === null) {
              setDraft(doc);
            }
          }}
        />
        <NumberField
          label="Минимальная сумма, $"
          value={doc.min_sum_usd}
          onChange={(v) => {
            set({ min_sum_usd: v });
          }}
        />
      </section>
      <LimitsSection doc={doc} onChange={set} />
      <SaveBar
        changed={changed}
        saving={save.isPending}
        onSave={() => {
          setConfirming(true);
        }}
        onReset={discard}
      >
        {invalid && !confirming ? (
          <p role="alert" className="text-danger text-sm">
            {invalid}
          </p>
        ) : null}
        {save.isError && !confirming ? (
          <p role="alert" className="text-danger text-sm">
            {payoutErrorText(save.error)}
          </p>
        ) : null}
      </SaveBar>
      {confirming ? (
        <Modal
          title={turningOff ? "Выключить выкуп?" : "Сохранить настройки выкупа?"}
          description={
            turningOff
              ? "Пользователи не смогут продавать скины. Начатые продажи дойдут до конца."
              : "Действует на новые продажи."
          }
          busy={save.isPending}
          onClose={() => {
            setConfirming(false);
          }}
        >
          {invalid ? (
            <p role="alert" className="text-danger text-sm">
              {invalid}
            </p>
          ) : null}
          {save.isError ? (
            <p role="alert" className="text-danger text-sm">
              {payoutErrorText(save.error)}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                setConfirming(false);
              }}
            >
              Отмена
            </Button>
            <Button
              disabled={save.isPending}
              onClick={() => {
                submit();
              }}
            >
              {turningOff ? "Да, выключить" : "Да, сохранить"}
            </Button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
