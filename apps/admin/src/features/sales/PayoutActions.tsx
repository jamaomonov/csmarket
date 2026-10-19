/**
 * The decisions on a payout, each behind an inline confirm that says what exactly happens and
 * one `Idempotency-Key` per submission: «Выплачено» (restates amount, card and seller; a banned
 * account or a frozen wallet needs a reason), «Отклонить», «Отменить (откат)» when the sale was
 * reverted, and «Вернуть в очередь» for a decision of the last 10 minutes.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PAYOUTS_KEY, payoutKey, saleKey } from "./keys";
import { CARD_BRANDS, last4, payoutErrorText } from "./labels";
import {
  cancelPayout,
  markPaid,
  type PayoutDetail as Detail,
  rejectPayout,
  undoPayout,
} from "./payoutsApi";

import { useAuthStore } from "@/features/auth/authStore";
import { DASHBOARD_KEY } from "@/features/dashboard/keys";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime, formatSum } from "@/lib/format";

type Panel = "none" | "paid" | "reject" | "cancel" | "undo";

const TEXT_LABEL: Record<Exclude<Panel, "none">, string> = {
  paid: "Комментарий (номер чека банка)",
  reject: "Причина (видят только администраторы)",
  cancel: "Причина",
  undo: "Почему возвращаете",
};

const CONFIRM: Record<Exclude<Panel, "none">, string> = {
  paid: "Да, выплачено",
  reject: "Да, отклонить",
  cancel: "Да, отменить",
  undo: "Да, вернуть в очередь",
};

function consequence(panel: Exclude<Panel, "none">, d: Detail): string {
  const r = d.request;
  const card = `${CARD_BRANDS[r.card_type]} •••• ${last4(r.card_masked)}`;
  const who = r.user.display_name ?? "без имени";
  const back = formatSum(Number(r.amount_uzs) + Number(r.fee_uzs));
  switch (panel) {
    case "paid":
      return `Выплачено ${formatSum(r.amount_uzs)} на ${card}, получатель ${who}?`;
    case "reject":
      return `${back} будут зачислены на баланс пользователя ${who}.`;
    case "cancel":
      return "Ничего не выплачивается, продажа станет «откат обмена», пользователь получит письмо об отмене.";
    case "undo":
      return r.status === "rejected"
        ? `${back} спишутся с баланса пользователя, если он их ещё не потратил. Заявка вернётся «К выплате».`
        : "Заявка вернётся «К выплате». Если деньги уже ушли на карту — не возвращайте.";
  }
}

export function PayoutActions({ detail, onStale }: { detail: Detail; onStale: () => void }) {
  const qc = useQueryClient();
  const meId = useAuthStore((s) => s.me?.id ?? null);
  const id = detail.request.id;
  const [panel, setPanel] = useState<Panel>("none");
  const [text, setText] = useState("");
  const [override, setOverride] = useState("");
  const key = useIdempotencyKey("admin-payout");
  const act = useMutation({
    mutationFn: (p: Exclude<Panel, "none">): Promise<Detail> => {
      const value = text.trim();
      const k = key.keyFor(JSON.stringify({ id, p, value, override }));
      switch (p) {
        case "paid":
          return markPaid(id, value || null, k, override.trim() || null);
        case "reject":
          return rejectPayout(id, value, k);
        case "cancel":
          return cancelPayout(id, value, k);
        case "undo":
          return undoPayout(id, value, k);
      }
    },
    onSuccess: (next) => {
      key.reset();
      qc.setQueryData(payoutKey(id), next);
      void qc.invalidateQueries({ queryKey: PAYOUTS_KEY });
      void qc.invalidateQueries({ queryKey: saleKey(detail.sale.number) });
      void qc.invalidateQueries({ queryKey: DASHBOARD_KEY });
      setPanel("none");
      setText("");
      setOverride("");
    },
    onError: () => {
      onStale();
    },
  });
  const by = detail.request.claimed_by ?? null;
  const takenByOther = by !== null && by.id !== meId;
  const undoUntil = detail.undo_until ?? null;
  const open = (p: Panel) => {
    setPanel(p);
    setText("");
    act.reset();
  };
  const needsText = panel === "reject" || panel === "cancel" || panel === "undo";
  const needsOverride = panel === "paid" && detail.paid_needs_override === true;
  const blocked =
    act.isPending || (needsText && text.trim() === "") || (needsOverride && override.trim() === "");
  if (!detail.can_decide && undoUntil === null) return null;
  return (
    <section className="flex flex-col gap-3" aria-label="Решение">
      {/* On a phone the decision stays at the bottom of the screen while the card scrolls. */}
      <div className="bg-bg/95 border-border sticky bottom-0 z-20 -mx-4 flex flex-wrap gap-2 border-t px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none [&>button]:flex-1 sm:[&>button]:flex-none">
        {detail.can_decide ? (
          <>
            <Button
              disabled={takenByOther}
              onClick={() => {
                open("paid");
              }}
            >
              Выплачено
            </Button>
            <Button
              variant="secondary"
              disabled={takenByOther}
              onClick={() => {
                open("reject");
              }}
            >
              Отклонить
            </Button>
          </>
        ) : null}
        {detail.can_cancel === true ? (
          <Button
            variant="secondary"
            disabled={takenByOther}
            onClick={() => {
              open("cancel");
            }}
          >
            Отменить (откат)
          </Button>
        ) : null}
        {undoUntil !== null ? (
          <Button
            variant="secondary"
            onClick={() => {
              open("undo");
            }}
          >
            Вернуть в очередь
          </Button>
        ) : null}
      </div>
      {takenByOther && detail.can_decide ? (
        <p className="text-fg-muted text-sm">Сначала «Забрать себе» — заявку платит другой.</p>
      ) : null}
      {undoUntil !== null && panel === "none" ? (
        <p className="text-fg-muted text-sm">
          Ошиблись? Вернуть можно до {formatDateTime(undoUntil).slice(-5)}.
        </p>
      ) : null}
      {panel !== "none" ? (
        <div
          role="group"
          aria-label="Подтверждение"
          className="border-border bg-surface flex flex-col gap-3 rounded-lg border p-4"
        >
          <p className="font-medium">{consequence(panel, detail)}</p>
          {needsOverride ? (
            <label className="text-danger flex flex-col gap-1 text-sm">
              {detail.request.flags?.includes("rolled_back") === true
                ? "Обмен отменён — скины вернулись к продавцу."
                : "Аккаунт заблокирован или кошелёк заморожен."}{" "}
              Почему всё равно платите?
              <textarea
                maxLength={500}
                value={override}
                onChange={(e) => {
                  setOverride(e.target.value);
                }}
                className="border-danger bg-bg text-fg rounded-md border p-2"
              />
            </label>
          ) : null}
          <label className="flex flex-col gap-1 text-sm">
            {TEXT_LABEL[panel]}
            <textarea
              maxLength={500}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
              }}
              className="border-border bg-bg rounded-md border p-2"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button
              variant={panel === "paid" ? "primary" : "danger"}
              disabled={blocked}
              onClick={() => {
                act.mutate(panel);
              }}
            >
              {CONFIRM[panel]}
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setPanel("none");
              }}
            >
              Отмена
            </Button>
          </div>
          {act.isError ? (
            <p role="alert" className="text-danger text-sm">
              {payoutErrorText(act.error)}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
