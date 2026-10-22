/**
 * «Риск» on the user card: what the user put in through the kassas, their own limit, a «trusted»
 * pass and a kassa block (spec 2026-10-21-payment-risk-limits). Fetches and saves on its own.
 */
import { Button, Switch } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { getRisk, saveRisk, type RiskPolicy, type RiskPolicyIn } from "./api";
import { errorText } from "./labels";
import { useIdempotencyKey } from "./useIdempotencyKey";

import { MoneyField } from "@/components/MoneyInput";
import { countChanges } from "@/components/SaveBar";
import { SavedNotice } from "@/components/SavedNotice";
import { Section } from "@/components/Section";
import { formatSum } from "@/lib/format";

interface Draft {
  trusted: boolean;
  kassaBlocked: boolean;
  max: string;
  hours: string;
  note: string;
}

const MAX_UZS = 1_000_000_000;
const MAX_HOURS = 720;
const NOTE_MAX = 500;

const toDraft = (p: RiskPolicy): Draft => ({
  trusted: p.trusted,
  kassaBlocked: p.kassa_blocked,
  max: p.max_amount_uzs ?? "",
  hours: String(p.window_hours),
  note: p.note ?? "",
});

/** The request body, or `null` when a field is not a whole number in range. */
function toBody(d: Draft): RiskPolicyIn | null {
  const max = d.max.trim();
  const maxOk =
    max === "" || (/^\d{1,10}$/.test(max) && Number(max) >= 1 && Number(max) <= MAX_UZS);
  const hoursOk = /^\d{1,4}$/.test(d.hours) && Number(d.hours) >= 1 && Number(d.hours) <= MAX_HOURS;
  if (!maxOk || !hoursOk) return null;
  const note = d.note.trim();
  return {
    trusted: d.trusted,
    kassa_blocked: d.kassaBlocked,
    max_amount_uzs: max === "" ? null : Number(max),
    window_hours: Number(d.hours),
    note: note === "" ? null : note,
  };
}

export function RiskBlock({ userId }: { userId: string }) {
  const qc = useQueryClient();
  const key = useIdempotencyKey("admin-user-risk");
  const queryKey = ["admin", "users", "risk", userId] as const;
  const risk = useQuery({ queryKey, queryFn: () => getRisk(userId) });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [invalid, setInvalid] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const save = useMutation({
    mutationFn: (body: RiskPolicyIn) => saveRisk(userId, body, key.keyFor(JSON.stringify(body))),
    onSuccess: (out) => {
      key.reset();
      setSavedAt(new Date());
      qc.setQueryData(queryKey, out);
      setDraft(null);
    },
  });

  if (risk.isError) {
    return (
      <Section title="Риск">
        <p role="alert" className="text-danger text-sm">
          {errorText(risk.error)}
        </p>
      </Section>
    );
  }
  if (!risk.data) {
    return (
      <Section title="Риск">
        <p className="text-fg-muted text-sm">Загрузка…</p>
      </Section>
    );
  }
  const p = risk.data;
  const d = draft ?? toDraft(p);
  const edit = (change: Partial<Draft>) => {
    setDraft({ ...d, ...change });
  };
  const dirty = draft !== null && countChanges(toDraft(p), draft) > 0;
  const submit = () => {
    const body = toBody(d);
    setInvalid(body === null);
    if (body !== null) save.mutate(body);
  };

  return (
    <Section title="Риск">
      <div className="space-y-3">
        <p className="text-sm" data-testid="risk-money-in">
          Внесено через кассы: 24 ч {formatSum(p.money_in_24h_uzs)} / 7 дней{" "}
          {formatSum(p.money_in_7d_uzs)}
        </p>
        {p.open_holds > 0 && (
          <p className="text-sm">
            На проверке: {p.open_holds}{" "}
            <Link className="text-accent hover:underline" to="/payment-holds">
              открыть
            </Link>
          </p>
        )}
        <SavedNotice at={savedAt} />
        <div className="flex flex-col">
          <Switch
            label="Доверенный"
            states={["да", "нет"]}
            hint="без лимитов"
            checked={d.trusted}
            onCheckedChange={(v) => {
              edit({ trusted: v });
            }}
          />
          <Switch
            label="Запретить оплату кассой"
            states={["запрещена", "разрешена"]}
            checked={d.kassaBlocked}
            onCheckedChange={(v) => {
              edit({ kassaBlocked: v });
            }}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <MoneyField
            label="Личный лимит"
            unit="сум"
            value={d.max}
            onChange={(v) => {
              edit({ max: v });
            }}
          />
          <MoneyField
            label="Окно"
            unit="ч"
            value={d.hours}
            onChange={(v) => {
              edit({ hours: v });
            }}
          />
        </div>
        <p className="text-fg-muted text-xs">Пусто — личного лимита нет, работает лимит кассы.</p>
        <label className="flex flex-col gap-1 text-sm">
          Заметка
          <textarea
            aria-label="Заметка"
            value={d.note}
            maxLength={NOTE_MAX}
            rows={2}
            onChange={(e) => {
              edit({ note: e.target.value });
            }}
            className="border-border bg-bg w-full rounded-md border px-3 py-1.5"
          />
        </label>
        {invalid && (
          <p role="alert" className="text-danger text-sm">
            Лимит — целое число сумов от 1 до 1 000 000 000 или пусто; окно — от 1 до 720 часов.
          </p>
        )}
        {save.isError && (
          <p role="alert" className="text-danger text-sm">
            {errorText(save.error)}
          </p>
        )}
        {dirty && (
          <div className="flex gap-2">
            <Button type="button" size="sm" disabled={save.isPending} onClick={submit}>
              Сохранить
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={save.isPending}
              onClick={() => {
                setDraft(null);
                setInvalid(false);
              }}
            >
              Сбросить
            </Button>
          </div>
        )}
      </div>
    </Section>
  );
}
