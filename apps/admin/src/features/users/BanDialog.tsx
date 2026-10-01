/** Block or unblock an account; the reason is required and lands in the audit log. */
import { Button } from "@csmarket/ui";
import { useMutation } from "@tanstack/react-query";
import { type SubmitEvent, useId, useRef, useState } from "react";

import { type AdminUserCard, banUser, unbanUser } from "./api";
import { errorText } from "./labels";
import { useIdempotencyKey } from "./useIdempotencyKey";

import { ApiError } from "@/lib/api";

const REASON_MIN = 3;
const REASON_MAX = 500;

const CONFLICTS: Record<string, string> = {
  ban_self: "Себя заблокировать нельзя.",
  ban_admin: "Администратора заблокировать нельзя.",
  already_banned: "Пользователь уже заблокирован.",
  not_banned: "Пользователь уже разблокирован.",
};

function conflictText(err: unknown): string {
  const code = err instanceof ApiError ? err.code : undefined;
  return (code !== undefined ? CONFLICTS[code] : undefined) ?? errorText(err);
}

interface BanDialogProps {
  userId: string;
  /** `true` offers to unblock, `false` to block. */
  banned: boolean;
  onDone: (card: AdminUserCard) => void;
  /** A 409 means the card is stale; the parent refetches it. */
  onConflict: () => void;
  onClose: () => void;
}

export function BanDialog({ userId, banned, onDone, onConflict, onClose }: BanDialogProps) {
  const titleId = useId();
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const idem = useIdempotencyKey(banned ? "admin-unban" : "admin-ban");
  const inFlight = useRef(false);
  const mutation = useMutation({
    mutationFn: (v: { reason: string; key: string }) =>
      banned ? unbanUser(userId, v.reason, v.key) : banUser(userId, v.reason, v.key),
    onSuccess: (card) => {
      idem.reset();
      onDone(card);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) onConflict();
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
    mutation.mutate({ reason: text, key: idem.keyFor(text) });
  };

  const title = banned ? "Разблокировать пользователя" : "Заблокировать пользователя";
  const action = banned ? "Разблокировать" : "Заблокировать";
  const error = formError ?? (mutation.isError ? conflictText(mutation.error) : null);
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
