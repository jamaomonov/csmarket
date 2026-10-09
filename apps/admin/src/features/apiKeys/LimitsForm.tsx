/** Edit a key's per-minute limits: an empty field = the default. Needs a reason for the audit log. */
import { Button } from "@csmarket/ui";
import { useMutation } from "@tanstack/react-query";
import { type SubmitEvent, useRef, useState } from "react";

import { type AdminApiKeyCard, type AdminLimitsBody, type LimitName, setApiKeyLimits } from "./api";
import { errorText, LIMIT_DEFAULTS, LIMIT_LABELS, LIMIT_NAMES } from "./labels";
import { type IdempotencyKey } from "../users/useIdempotencyKey";

const MAX = 10_000;
const REASON_MIN = 3;

type Draft = Record<LimitName, string>;

interface LimitsFormProps {
  keyId: string;
  /** The limits the key sets itself; the others show the default as a placeholder. */
  current: Partial<Record<LimitName, number>>;
  idem: IdempotencyKey;
  onDone: (card: AdminApiKeyCard) => void;
  onClose: () => void;
}

function parse(text: string): number | null | "bad" {
  const t = text.trim();
  if (t === "") return null;
  if (!/^\d+$/.test(t)) return "bad";
  const n = Number(t);
  return n >= 1 && n <= MAX ? n : "bad";
}

export function LimitsForm({ keyId, current, idem, onDone, onClose }: LimitsFormProps) {
  const [draft, setDraft] = useState<Draft>(() => {
    const init = {} as Draft;
    for (const name of LIMIT_NAMES) init[name] = current[name]?.toString() ?? "";
    return init;
  });
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mutation = useMutation({
    mutationFn: (v: { body: AdminLimitsBody; key: string }) =>
      setApiKeyLimits(keyId, v.body, v.key),
    onSuccess: (card) => {
      idem.reset();
      onDone(card);
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });

  const onSubmit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inFlight.current) return;
    const text = reason.trim();
    const values = {} as Record<LimitName, number | null>;
    for (const name of LIMIT_NAMES) {
      const v = parse(draft[name]);
      if (v === "bad") {
        setFormError(
          `Лимит «${LIMIT_LABELS[name]}»: целое число от 1 до ${String(MAX)} или пусто.`,
        );
        return;
      }
      values[name] = v;
    }
    if (text.length < REASON_MIN) {
      setFormError("Напишите причину — от 3 символов.");
      return;
    }
    setFormError(null);
    inFlight.current = true;
    const body: AdminLimitsBody = { ...values, reason: text };
    mutation.mutate({ body, key: idem.keyFor(JSON.stringify({ keyId, body })) });
  };

  const error = formError ?? (mutation.isError ? errorText(mutation.error) : null);
  return (
    <form onSubmit={onSubmit} className="border-border max-w-md space-y-3 rounded-lg border p-4">
      {LIMIT_NAMES.map((name) => (
        <label key={name} className="flex flex-col gap-1 text-sm">
          {LIMIT_LABELS[name]}
          <input
            type="text"
            inputMode="numeric"
            value={draft[name]}
            placeholder={`${String(LIMIT_DEFAULTS[name])} (по умолчанию)`}
            onChange={(e) => {
              setDraft((d) => ({ ...d, [name]: e.target.value }));
            }}
            className="border-border bg-bg rounded-md border px-3 py-2 text-base"
          />
        </label>
      ))}
      <label className="flex flex-col gap-1 text-sm">
        Причина
        <textarea
          value={reason}
          maxLength={500}
          rows={2}
          onChange={(e) => {
            setReason(e.target.value);
          }}
          className="border-border bg-bg rounded-md border px-3 py-2 text-base"
        />
      </label>
      <p className="text-fg-muted text-xs">Её увидят в журнале. Без личных данных.</p>
      {error !== null && (
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" disabled={mutation.isPending} onClick={onClose}>
          Отмена
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          Сохранить
        </Button>
      </div>
    </form>
  );
}
