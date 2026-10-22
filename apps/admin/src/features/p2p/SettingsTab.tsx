/**
 * «Подключение и лимиты»: the connection's state, the trusted Telegram ids and the buyer's
 * limits. Sums are `MoneyField`s (grouped, the unit on the right); one `SaveBar` like every
 * settings page, shown only when something changed.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getP2PSettings, type P2PSettings, saveP2PSettings } from "./api";
import { settingsKey } from "./keys";

import { MoneyField } from "@/components/MoneyInput";
import { countChanges, SaveBar } from "@/components/SaveBar";
import { SavedNotice } from "@/components/SavedNotice";
import { Row, Section } from "@/components/Section";
import { StatusChip } from "@/components/StatusChip";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

type Key = keyof P2PSettings;

const IDS: { key: Key; label: string }[] = [
  { key: "humo_bot_user_id", label: "Telegram id бота HUMO" },
  { key: "owner_telegram_user_id", label: "Ваш Telegram id" },
];

const LIMITS: { key: Key; label: string; unit: string }[] = [
  { key: "min_amount_uzs", label: "Минимум", unit: "сум" },
  { key: "max_amount_uzs", label: "Максимум", unit: "сум" },
  { key: "daily_amount_uzs", label: "Сумма в день", unit: "сум" },
  { key: "daily_count", label: "Пополнений в день", unit: "шт" },
];

const ALL: Key[] = [...IDS, ...LIMITS].map((f) => f.key);

export function SettingsTab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: settingsKey, queryFn: getP2PSettings });
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const key = useIdempotencyKey("admin-p2p-settings");
  const save = useMutation({
    mutationFn: (body: P2PSettings) => saveP2PSettings(body, key.keyFor(JSON.stringify(body))),
    onSuccess: (out) => {
      key.reset();
      qc.setQueryData(settingsKey, out);
      setDraft(null);
      setSavedAt(new Date());
    },
  });
  if (q.isPending) return <p className="text-fg-muted">Загрузка…</p>;
  if (q.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(q.error)}
      </p>
    );
  }
  const s = q.data;
  const savedValue = (k: Key): string => (s[k] === null ? "" : String(s[k]));
  const value = (k: Key): string => draft?.[k] ?? savedValue(k);
  const changed =
    draft === null
      ? 0
      : countChanges(
          Object.fromEntries(ALL.map((k) => [k, savedValue(k)])),
          Object.fromEntries(ALL.map((k) => [k, value(k)])),
        );
  const edit = (k: Key, v: string) => {
    setDraft({ ...(draft ?? {}), [k]: v });
  };
  const body = (): P2PSettings => {
    const n = (k: Key): number | null => {
      const v = value(k).replace(/\D/g, "");
      return v === "" ? null : Number(v);
    };
    return {
      humo_bot_user_id: n("humo_bot_user_id"),
      owner_telegram_user_id: n("owner_telegram_user_id"),
      min_amount_uzs: n("min_amount_uzs") ?? 0,
      max_amount_uzs: n("max_amount_uzs") ?? 0,
      daily_count: n("daily_count") ?? 0,
      daily_amount_uzs: n("daily_amount_uzs") ?? 0,
    };
  };
  return (
    <div className="max-w-2xl space-y-4">
      <Section title="Подключение">
        <dl>
          <Row label="Бот">
            <StatusChip tone={s.connected ? "success" : "danger"}>
              {s.connected ? "подключено" : "не подключено"}
            </StatusChip>
          </Row>
          <Row label="Последнее уведомление">
            {s.last_received_at ? formatDateTime(s.last_received_at) : "ещё не было"}
          </Row>
        </dl>
      </Section>
      <SavedNotice at={savedAt} />
      <Section title="Доступ">
        <div className="grid gap-3 sm:grid-cols-2">
          {IDS.map(({ key: k, label }) => (
            <label key={k} className="flex flex-col gap-1 text-sm">
              {label}
              <input
                inputMode="numeric"
                autoComplete="off"
                value={value(k)}
                placeholder="не задан"
                onChange={(e) => {
                  edit(k, e.target.value);
                }}
                className="border-border bg-bg h-10 rounded-md border px-3 tabular-nums"
              />
            </label>
          ))}
        </div>
      </Section>
      <Section title="Лимиты пополнения">
        <div className="grid gap-3 sm:grid-cols-2">
          {LIMITS.map(({ key: k, label, unit }) => (
            <MoneyField
              key={k}
              label={label}
              unit={unit}
              value={value(k)}
              onChange={(v) => {
                edit(k, v);
              }}
            />
          ))}
        </div>
      </Section>
      <SaveBar
        changed={changed}
        saving={save.isPending}
        onSave={() => {
          save.mutate(body());
        }}
        onReset={() => {
          setDraft(null);
          save.reset();
        }}
      >
        {save.isError && (
          <p role="alert" className="text-danger text-sm">
            {errorText(save.error)}
          </p>
        )}
      </SaveBar>
    </div>
  );
}
