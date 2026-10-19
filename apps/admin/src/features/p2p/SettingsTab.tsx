/** «Настройки»: the trusted Telegram ids, the buyer's limits and the connection's state. */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getP2PSettings, type P2PSettings, saveP2PSettings } from "./api";
import { settingsKey } from "./keys";

import { SavedNotice } from "@/components/SavedNotice";
import { Row, Section } from "@/components/Section";
import { StatusChip } from "@/components/StatusChip";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

const FIELDS: { key: keyof P2PSettings; label: string }[] = [
  { key: "humo_bot_user_id", label: "Telegram id бота HUMO" },
  { key: "owner_telegram_user_id", label: "Ваш Telegram id" },
  { key: "min_amount_uzs", label: "Минимум, сум" },
  { key: "max_amount_uzs", label: "Максимум, сум" },
  { key: "daily_count", label: "Пополнений в день" },
  { key: "daily_amount_uzs", label: "Сумма в день, сум" },
];

const OPTIONAL = new Set<keyof P2PSettings>(["humo_bot_user_id", "owner_telegram_user_id"]);

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
  const value = (k: keyof P2PSettings): string => draft?.[k] ?? (s[k] === null ? "" : String(s[k]));
  const body = (): P2PSettings => {
    const n = (k: keyof P2PSettings): number | null => {
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
      <Section title="Лимиты и доступ">
        <div className="grid gap-3 sm:grid-cols-2">
          {FIELDS.map(({ key: k, label }) => (
            <label key={k} className="flex flex-col gap-1 text-sm">
              {label}
              <input
                inputMode="numeric"
                value={value(k)}
                placeholder={OPTIONAL.has(k) ? "не задан" : ""}
                onChange={(e) => {
                  setDraft({ ...(draft ?? {}), [k]: e.target.value });
                }}
                className="border-border bg-bg h-10 rounded-md border px-3"
              />
            </label>
          ))}
        </div>
        {save.isError && (
          <p role="alert" className="text-danger mt-2 text-sm">
            {errorText(save.error)}
          </p>
        )}
        <div className="mt-3 flex items-center gap-3">
          <Button
            disabled={draft === null || save.isPending}
            onClick={() => {
              save.mutate(body());
            }}
          >
            Сохранить
          </Button>
          <SavedNotice at={savedAt} />
        </div>
      </Section>
    </div>
  );
}
