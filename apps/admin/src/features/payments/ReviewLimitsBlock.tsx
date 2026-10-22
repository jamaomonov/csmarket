/**
 * «Лимит без проверки»: how much one user may pass through each kassa in a window. Over it a
 * payment is held, never refused (spec 2026-10-21-payment-risk-limits). Saved with the version
 * the edit started from, so a stale tab cannot write old numbers back. The draft and the save
 * live in `useReviewLimits`, so «Настройки оплаты» saves it with the fees from one save bar.
 */
import { Switch } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getReviewLimits, type KassaLimitIn, type ReviewLimitsOut, saveReviewLimits } from "./api";
import { SETTINGS_KASSAS } from "./kinds";

import { MoneyInput } from "@/components/MoneyInput";
import { countChanges } from "@/components/SaveBar";
import { Section } from "@/components/Section";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";

const KEY = ["admin", "payments", "review-limits"] as const;

const KASSAS = SETTINGS_KASSAS;
const MAX_UZS = 1_000_000_000;
const MAX_HOURS = 720;

export const LIMITS_INVALID =
  "Сумма — целое число сумов (от 1 до 1 000 000 000), окно — целое число часов (от 1 до 720).";

export interface LimitRow {
  provider: string;
  enabled: boolean;
  max: string;
  hours: string;
}

const isWhole = (v: string, max: number): boolean =>
  /^\d{1,10}$/.test(v) && Number(v) >= 1 && Number(v) <= max;

function rowsOf(data: ReviewLimitsOut): LimitRow[] {
  return KASSAS.map(({ slug }) => {
    const l = data.limits.find((x) => x.provider === slug);
    return {
      provider: slug,
      enabled: l?.enabled ?? true,
      max: l?.max_amount_uzs ?? "2000000",
      hours: String(l?.window_hours ?? 24),
    };
  });
}

/** The limits' saved rows, the draft over them and the save. */
export function useReviewLimits() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: getReviewLimits });
  const [draft, setDraft] = useState<LimitRow[] | null>(null);
  const key = useIdempotencyKey("admin-review-limits");
  const version = query.data?.updated_at ?? null;
  const mutation = useMutation({
    mutationFn: (rows: KassaLimitIn[]) =>
      saveReviewLimits(rows, version, key.keyFor(JSON.stringify(rows))),
    onSuccess: (out) => {
      key.reset();
      qc.setQueryData(KEY, out);
      setDraft(null);
    },
  });
  const saved = query.data ? rowsOf(query.data) : null;
  const rows = draft ?? saved;
  const changed = saved !== null && draft !== null ? countChanges(saved, draft) : 0;
  return {
    query,
    rows,
    changed,
    setDraft,
    mutation,
    valid: (): boolean =>
      (rows ?? []).every((r) => isWhole(r.max, MAX_UZS) && isWhole(r.hours, MAX_HOURS)),
    save: (): Promise<ReviewLimitsOut> =>
      mutation.mutateAsync(
        (rows ?? []).map((r) => ({
          provider: r.provider,
          enabled: r.enabled,
          max_amount_uzs: Number(r.max),
          window_hours: Number(r.hours),
        })),
      ),
    reset: (): void => {
      setDraft(null);
      mutation.reset();
    },
  };
}

interface ReviewLimitsBlockProps {
  limits: ReturnType<typeof useReviewLimits>;
}

export function ReviewLimitsBlock({ limits }: ReviewLimitsBlockProps) {
  const { query, rows } = limits;
  if (query.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(query.error)}
      </p>
    );
  }
  if (rows === null) return <p className="text-fg-muted">Загрузка…</p>;
  const patch = (slug: string, change: Partial<LimitRow>) => {
    limits.setDraft(rows.map((r) => (r.provider === slug ? { ...r, ...change } : r)));
  };
  const head = "text-fg-muted pb-1 text-left text-xs font-normal";
  return (
    <Section title="Лимит без проверки">
      <p className="text-fg-muted mb-3 text-sm">
        Сколько один пользователь может провести через кассу за окно. Свыше — платёж ждёт решения в
        «На проверке».
      </p>
      <table className="-mx-2 w-full border-separate border-spacing-x-2 border-spacing-y-1 text-sm">
        <thead>
          <tr>
            <th scope="col" className={head}>
              Касса
            </th>
            <th scope="col" className={head}>
              Вкл
            </th>
            <th scope="col" className={head}>
              Сумма
            </th>
            <th scope="col" className={`${head} w-24`}>
              Окно
            </th>
          </tr>
        </thead>
        <tbody>
          {KASSAS.map(({ slug, label, short }) => {
            const r = rows.find((x) => x.provider === slug);
            if (r === undefined) return null;
            return (
              <tr key={slug}>
                <th scope="row" className="text-left font-medium">
                  {short}
                </th>
                <td className="w-12">
                  <Switch
                    label={<span className="sr-only">{label}: включён</span>}
                    checked={r.enabled}
                    onCheckedChange={(on) => {
                      patch(slug, { enabled: on });
                    }}
                  />
                </td>
                <td>
                  <MoneyInput
                    label={`${label}: сумма`}
                    unit="сум"
                    className="w-full"
                    value={r.max}
                    onChange={(v) => {
                      patch(slug, { max: v });
                    }}
                  />
                </td>
                <td>
                  <MoneyInput
                    label={`${label}: окно`}
                    unit="ч"
                    className="w-full"
                    value={r.hours}
                    onChange={(v) => {
                      patch(slug, { hours: v });
                    }}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Section>
  );
}
