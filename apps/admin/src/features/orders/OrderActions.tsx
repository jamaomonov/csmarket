/**
 * «Разобрано», «Вернуть деньги на баланс», «Повторить покупку». The refund and the retry are
 * offered only when the API says they would succeed (`can_refund` / `can_retry`); each goes
 * through a confirm step and sends one `Idempotency-Key` per confirmed submission. An open
 * confirm step closes by itself when a refetch says its action is no longer possible.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useRef, useState } from "react";

import { type AdminOrderDetail, refundOrder, resolveOrder, retryOrder } from "./api";
import { detailKey, ORDERS_LIST_KEY, TRADES_KEY } from "./keys";
import { isOrderConflict, orderErrorText } from "./labels";

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

interface OrderActionsProps {
  detail: AdminOrderDetail;
  /** The page's refetch, run after a 409 so the buttons show what is really possible. */
  onStale: () => void;
}

function ConfirmBox({ children }: { children: ReactNode }) {
  return (
    <div
      role="group"
      aria-label="Подтверждение"
      data-testid="order-confirm"
      className="border-border bg-surface space-y-3 rounded-lg border p-4"
    >
      {children}
    </div>
  );
}

export function OrderActions({ detail, onStale }: OrderActionsProps) {
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
      void qc.invalidateQueries({ queryKey: ORDERS_LIST_KEY });
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
  if (!needsResolve && !detail.can_refund && !detail.can_retry && error === null) return null;

  const busy = mutation.isPending;
  const cancel = (
    <Button
      variant="ghost"
      disabled={busy}
      onClick={() => {
        setPanel("none");
      }}
    >
      Отмена
    </Button>
  );

  return (
    <section aria-label="Действия" className="space-y-3">
      <h2 className="text-lg font-semibold">Действия</h2>
      <div className="flex flex-wrap gap-2">
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
        {detail.can_refund && (
          <Button
            variant="danger"
            onClick={() => {
              open("refund");
            }}
          >
            Вернуть деньги на баланс
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
      </div>
      {panel === "resolve" && needsResolve && (
        <form
          className="border-border bg-surface space-y-3 rounded-lg border p-4"
          data-testid="order-resolve-form"
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
          <p className="text-fg-muted text-xs">Что нашли в кабинете Waxpeer. Без личных данных.</p>
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>
              Сохранить
            </Button>
            {cancel}
          </div>
        </form>
      )}
      {panel === "refund" && detail.can_refund && (
        <ConfirmBox>
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
          <div className="flex gap-2">
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => {
                submit("refund", null);
              }}
            >
              Вернуть
            </Button>
            {cancel}
          </div>
        </ConfirmBox>
      )}
      {panel === "retry" && detail.can_retry && (
        <ConfirmBox>
          <p>
            Сначала проверьте project id в кабинете Waxpeer — повтор купит скин, если покупки там
            нет.
          </p>
          <div className="flex gap-2">
            <Button
              disabled={busy}
              onClick={() => {
                submit("retry", null);
              }}
            >
              Повторить
            </Button>
            {cancel}
          </div>
        </ConfirmBox>
      )}
      {error !== null && (
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      )}
    </section>
  );
}
