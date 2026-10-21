/**
 * «Лимит без проверки»: how much one user may pass through each kassa in a window. Over it a
 * payment is held, never refused (spec 2026-10-21-payment-risk-limits). Saved with the version
 * the edit started from, so a stale tab cannot write old numbers back.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getReviewLimits, saveReviewLimits, type KassaLimitIn } from "./api";

import { SavedNotice } from "@/components/SavedNotice";
import { payoutErrorText } from "@/features/sales/labels";
import { NumberField } from "@/features/sales/SettingsParts";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";

const KEY = ["admin", "payments", "review-limits"] as const;

const KASSAS: readonly { slug: string; label: string }[] = [
  { slug: "payme", label: "Payme" },
  { slug: "click", label: "Click" },
  { slug: "uzum", label: "Uzum" },
  { slug: "p2p", label: "Перевод на карту (P2P)" },
];
const MAX_UZS = 1_000_000_000;
const MAX_HOURS = 720;

interface Row {
  provider: string;
  enabled: boolean;
  max: string;
  hours: string;
}

const isWhole = (v: string, max: number): boolean =>
  /^\d{1,10}$/.test(v) && Number(v) >= 1 && Number(v) <= max;

export function ReviewLimitsBlock() {
  const qc = useQueryClient();
  const limits = useQuery({ queryKey: KEY, queryFn: getReviewLimits });
  const [draft, setDraft] = useState<Row[] | null>(null);
  const [invalid, setInvalid] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const key = useIdempotencyKey("admin-review-limits");
  const version = limits.data?.updated_at ?? null;
  const save = useMutation({
    mutationFn: (rows: KassaLimitIn[]) =>
      saveReviewLimits(rows, version, key.keyFor(JSON.stringify(rows))),
    onSuccess: (out) => {
      key.reset();
      setSavedAt(new Date());
      qc.setQueryData(KEY, out);
      setDraft(null);
    },
  });
  if (limits.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(limits.error)}
      </p>
    );
  }
  if (!limits.data) return <p className="text-fg-muted">Загрузка…</p>;

  const saved = limits.data.limits;
  const rows: Row[] =
    draft ??
    KASSAS.map(({ slug }) => {
      const l = saved.find((x) => x.provider === slug);
      return {
        provider: slug,
        enabled: l?.enabled ?? true,
        max: l?.max_amount_uzs ?? "2000000",
        hours: String(l?.window_hours ?? 24),
      };
    });
  const patch = (slug: string, change: Partial<Row>) => {
    setDraft(rows.map((r) => (r.provider === slug ? { ...r, ...change } : r)));
  };
  const submit = () => {
    if (!rows.every((r) => isWhole(r.max, MAX_UZS) && isWhole(r.hours, MAX_HOURS))) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    save.mutate(
      rows.map((r) => ({
        provider: r.provider,
        enabled: r.enabled,
        max_amount_uzs: Number(r.max),
        window_hours: Number(r.hours),
      })),
    );
  };

  return (
    <section className="border-border bg-surface flex flex-col gap-3 rounded-lg border p-4">
      <h2 className="font-semibold">Лимит без проверки</h2>
      <p className="text-fg-muted text-sm">
        Сколько один пользователь может провести через кассу за окно. Свыше — платёж ждёт решения в
        «На проверке».
      </p>
      <SavedNotice at={savedAt} />
      <div className="flex flex-col gap-4">
        {KASSAS.map(({ slug, label }) => {
          const r = rows.find((x) => x.provider === slug);
          if (r === undefined) return null;
          return (
            <div key={slug} className="flex flex-wrap items-end gap-4">
              <span className="w-full text-sm font-medium sm:w-48 sm:pb-2">{label}</span>
              <label className="flex items-center gap-2 pb-2 text-sm">
                <input
                  type="checkbox"
                  aria-label={`${label}: включён`}
                  checked={r.enabled}
                  onChange={(e) => {
                    patch(slug, { enabled: e.target.checked });
                  }}
                />
                Включён
              </label>
              <NumberField
                label={`${label}: сумма, сум`}
                value={r.max}
                onChange={(v) => {
                  patch(slug, { max: v });
                }}
              />
              <NumberField
                label={`${label}: окно, ч`}
                value={r.hours}
                onChange={(v) => {
                  patch(slug, { hours: v });
                }}
              />
            </div>
          );
        })}
      </div>
      {invalid && (
        <p role="alert" className="text-danger text-sm">
          Сумма — целое число сумов (от 1 до 1 000 000 000), окно — целое число часов (от 1 до 720).
        </p>
      )}
      {save.isError && (
        <p role="alert" className="text-danger text-sm">
          {payoutErrorText(save.error)}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="button" disabled={draft === null || save.isPending} onClick={submit}>
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
    </section>
  );
}
