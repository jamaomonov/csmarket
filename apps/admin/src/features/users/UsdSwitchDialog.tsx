/** Switch the USD wallet on or off for an account; the reason lands in the audit log. */
import { Button } from "@csmarket/ui";
import { useMutation } from "@tanstack/react-query";
import { type SubmitEvent, useId, useRef, useState } from "react";

import { type AdminUserCard, switchUsdWallet } from "./api";
import { errorText } from "./labels";
import { type IdempotencyKey } from "./useIdempotencyKey";

const REASON_MIN = 3;
const REASON_MAX = 500;

interface UsdSwitchDialogProps {
  userId: string;
  /** The state to switch to. */
  enable: boolean;
  /** Owned by the card so a lost response retried after reopening replays. */
  idem: IdempotencyKey;
  onDone: (card: AdminUserCard) => void;
  onClose: () => void;
}

export function UsdSwitchDialog({ userId, enable, idem, onDone, onClose }: UsdSwitchDialogProps) {
  const titleId = useId();
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mutation = useMutation({
    mutationFn: (v: { reason: string; key: string }) =>
      switchUsdWallet(userId, enable, v.reason, v.key),
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
    if (text.length < REASON_MIN) {
      setFormError("Напишите причину — от 3 символов.");
      return;
    }
    setFormError(null);
    inFlight.current = true;
    mutation.mutate({ reason: text, key: idem.keyFor(JSON.stringify({ userId, enable, text })) });
  };

  const title = enable ? "Включить USD-кошелёк" : "Выключить USD-кошелёк";
  const error = formError ?? (mutation.isError ? errorText(mutation.error) : null);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      data-testid="usd-switch-dialog"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center sm:p-4"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !mutation.isPending) onClose();
      }}
    >
      <form
        onSubmit={onSubmit}
        className="border-border bg-surface max-h-[90vh] w-full space-y-4 overflow-y-auto rounded-t-xl border p-5 shadow-[var(--shadow-menu)] sm:max-w-md sm:rounded-xl"
      >
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        <p className="text-fg-muted text-sm">
          {enable
            ? "Пользователь сможет переводить сумы в доллары и покупать через API."
            : "Деньги на USD-балансе останутся. Перевод и покупки через API остановятся."}
        </p>
        <label className="flex flex-col gap-1 text-sm">
          Причина
          <textarea
            value={reason}
            maxLength={REASON_MAX}
            rows={3}
            autoFocus
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
          <Button
            type="submit"
            variant={enable ? "primary" : "danger"}
            disabled={mutation.isPending}
          >
            {enable ? "Включить" : "Выключить"}
          </Button>
        </div>
      </form>
    </div>
  );
}
