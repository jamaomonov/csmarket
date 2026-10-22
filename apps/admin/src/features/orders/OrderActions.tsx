/**
 * «Разобрано», «Вернуть деньги на баланс», «Повторить покупку». The refund and the retry are
 * offered only when the API says they would succeed (`can_refund` / `can_retry`); each goes
 * through a confirm step (a bottom sheet on a phone, `ConfirmSheet`) and sends one
 * `Idempotency-Key` per confirmed submission. An open confirm step closes by itself when a
 * refetch says its action is no longer possible.
 *
 * `useOrderActions` returns the buttons and the open step apart: the page puts the buttons in
 * its header on a wide screen and in the bottom `ActionBar` on a phone (admin UX audit §4).
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useRef, useState } from "react";

import { type AdminOrderDetail, refundOrder, resolveOrder, retryOrder } from "./api";
import { detailKey, TRADES_KEY } from "./keys";
import { isOrderConflict, orderErrorText } from "./labels";

import { CONFIRM_BUTTONS, ConfirmSheet, DANGER_OUTLINE } from "@/components/ConfirmSheet";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatSum, formatUsd } from "@/lib/format";

const NOTE_MAX = 500;

/** `"13.580000"` → `$13.580`: an API order's price is whole milli-USD, so nothing is lost. */
function milliUsd(value: string): string {
  return formatUsd(value.replace(/(\.\d{3})\d*$/, "$1"));
}

type Action = "resolve" | "refund" | "retry";
type Panel = "none" | Action;

interface Submission {
  action: Action;
  note: string | null;
  key: string;
}

export interface OrderActionsView {
  /** The action buttons; `null` when there is nothing to do. */
  buttons: ReactNode;
  /** The open confirm step and the last error; `null` when there is neither. */
  panel: ReactNode;
}

/**
 * @param onStale The page's refetch, run after a 409 so the buttons show what is really possible.
 */
export function useOrderActions(detail: AdminOrderDetail, onStale: () => void): OrderActionsView {
  const qc = useQueryClient();
  const { order, trade } = detail;
  const number = order.number;
  const [panel, setPanel] = useState<Panel>("none");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const resolveKey = useIdempotencyKey("admin-order-resolve");
  const refundKey = useIdempotencyKey("admin-order-refund");
  const retryKey = useIdempotencyKey("admin-order-retry");
  const keys = { resolve: resolveKey, refund: refundKey, retry: retryKey };

  const mutation = useMutation({
    mutationFn: (s: Submission): Promise<AdminOrderDetail> => {
      switch (s.action) {
        case "resolve":
          return resolveOrder(number, s.note, s.key);
        case "refund":
          return refundOrder(number, s.key);
        case "retry":
          return retryOrder(number, s.key);
      }
    },
    onSuccess: (next, s) => {
      keys[s.action].reset();
      qc.setQueryData(detailKey(number), next);
      void qc.invalidateQueries({ queryKey: TRADES_KEY });
      setPanel("none");
      setNote("");
      setError(null);
    },
    onError: (err) => {
      setError(orderErrorText(err));
      if (isOrderConflict(err)) {
        // The page was stale: show what is really possible now.
        setPanel("none");
        onStale();
      }
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });

  const open = (next: Panel) => {
    setError(null);
    setPanel(next);
  };
  const submit = (action: Action, body: string | null) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    mutation.mutate({
      action,
      note: body,
      key: keys[action].keyFor(JSON.stringify({ number, action, note: body })),
    });
  };

  // A Skinslink or LIS-SKINS order keeps its attention on its purchase.
  const watched = trade ?? detail.skinslink ?? detail.lisskins;
  const needsResolve =
    watched !== null && watched.attention_reason !== null && watched.resolved_at === null;
  if (!needsResolve && !detail.can_refund && !detail.can_retry && error === null) {
    return { buttons: null, panel: null };
  }

  const busy = mutation.isPending;
  const close = () => {
    setPanel("none");
  };
  const cancel = (
    <Button variant="ghost" disabled={busy} onClick={close}>
      Отмена
    </Button>
  );

  const buttons =
    needsResolve || detail.can_refund || detail.can_retry ? (
      <>
        {needsResolve && (
          <Button
            variant="secondary"
            onClick={() => {
              open("resolve");
            }}
          >
            Разобрано
          </Button>
        )}
        {detail.can_retry && (
          <Button
            variant="secondary"
            onClick={() => {
              open("retry");
            }}
          >
            Повторить покупку
          </Button>
        )}
        {detail.can_refund && (
          <Button
            variant="secondary"
            className={DANGER_OUTLINE}
            onClick={() => {
              open("refund");
            }}
          >
            Вернуть деньги на баланс
          </Button>
        )}
      </>
    ) : null;

  const panelNode = (
    <>
      {panel === "resolve" && needsResolve && (
        <ConfirmSheet title="Разобрано" busy={busy} onClose={close} testId="order-resolve-form">
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              const text = note.trim();
              submit("resolve", text === "" ? null : text);
            }}
          >
            <label className="flex flex-col gap-1 text-sm">
              Заметка
              <textarea
                value={note}
                maxLength={NOTE_MAX}
                rows={3}
                onChange={(e) => {
                  setNote(e.target.value);
                }}
                className="border-border bg-bg rounded-md border px-3 py-2 text-base"
              />
            </label>
            <p className="text-fg-muted text-xs">
              Что нашли в кабинете площадки. Без личных данных.
            </p>
            <div className={CONFIRM_BUTTONS}>
              {cancel}
              <Button type="submit" size="lg" disabled={busy}>
                Сохранить
              </Button>
            </div>
          </form>
        </ConfirmSheet>
      )}
      {panel === "refund" && detail.can_refund && (
        <ConfirmSheet title="Вернуть деньги" busy={busy} onClose={close} testId="order-confirm">
          <p>
            Вернуть{" "}
            {order.paid_with === "usd_wallet"
              ? milliUsd(order.price_usd)
              : formatSum(order.price_uzs)}{" "}
            на баланс покупателя?
          </p>
          {order.source !== "waxpeer" && (
            <p className="text-fg-muted text-xs">
              Сначала спросим поставщика: деньги вернутся, только если покупка не состоялась.
            </p>
          )}
          <div className={CONFIRM_BUTTONS}>
            {cancel}
            <Button
              variant="danger"
              size="lg"
              disabled={busy}
              onClick={() => {
                submit("refund", null);
              }}
            >
              Вернуть
            </Button>
          </div>
        </ConfirmSheet>
      )}
      {panel === "retry" && detail.can_retry && (
        <ConfirmSheet title="Повторить покупку" busy={busy} onClose={close} testId="order-confirm">
          <p>
            Сначала проверьте project id в кабинете Waxpeer — повтор купит скин, если покупки там
            нет.
          </p>
          <div className={CONFIRM_BUTTONS}>
            {cancel}
            <Button
              size="lg"
              disabled={busy}
              onClick={() => {
                submit("retry", null);
              }}
            >
              Повторить
            </Button>
          </div>
        </ConfirmSheet>
      )}
      {error !== null && (
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      )}
    </>
  );
  return { buttons, panel: panel === "none" && error === null ? null : panelNode };
}
