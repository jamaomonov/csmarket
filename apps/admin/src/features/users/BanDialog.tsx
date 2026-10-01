/** Block or unblock an account; the reason is required and lands in the audit log. */
import { Button } from "@csmarket/ui";
import { useMutation } from "@tanstack/react-query";
import { type SubmitEvent, useId, useRef, useState } from "react";

import { type AdminUserCard, banUser, unbanUser } from "./api";
import { errorText, STALE_BAN_CODES } from "./labels";
import { type IdempotencyKey } from "./useIdempotencyKey";

import { ApiError } from "@/lib/api";

const REASON_MIN = 3;
const REASON_MAX = 500;

interface BanDialogProps {
  userId: string;
  /** `true` offers to unblock, `false` to block. */
  banned: boolean;
  /** Owned by the card (per user and action) so a lost response retried after reopening replays. */
  idem: IdempotencyKey;
  onDone: (card: AdminUserCard) => void;
  /** The ban state changed under us: the parent closes the dialog, says why and refetches. */
  onStale: (message: string) => void;
  onClose: () => void;
}

export function BanDialog({ userId, banned, idem, onDone, onStale, onClose }: BanDialogProps) {
  const titleId = useId();
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mutation = useMutation({
    mutationFn: (v: { reason: string; key: string }) =>
      banned ? unbanUser(userId, v.reason, v.key) : banUser(userId, v.reason, v.key),
    onSuccess: (card) => {
      idem.reset();
      onDone(card);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code !== undefined && STALE_BAN_CODES.has(err.code)) {
        onStale(errorText(err));
      }
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
    const body = JSON.stringify({ userId, unban: banned, reason: text });
    mutation.mutate({ reason: text, key: idem.keyFor(body) });
  };

  const title = banned ? "Разблокировать пользователя" : "Заблокировать пользователя";
  const action = banned ? "Разблокировать" : "Заблокировать";
  const error = formError ?? (mutation.isError ? errorText(mutation.error) : null);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      data-testid="ban-dialog"
      className="fixed inset-0 z-10 flex items-center justify-center bg-black/50 p-4"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !mutation.isPending) onClose();
      }}
    >
      <form
        onSubmit={onSubmit}
        className="border-border bg-surface w-full max-w-md space-y-4 rounded-lg border p-5"
      >
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        <p className="text-fg-muted text-sm">
          {banned
            ? "Пользователь снова сможет войти."
            : "Пользователь выйдет на всех устройствах и не сможет войти."}
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
            variant={banned ? "primary" : "danger"}
            disabled={mutation.isPending}
          >
            {action}
          </Button>
        </div>
      </form>
    </div>
  );
}
