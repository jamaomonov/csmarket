/**
 * The decisions on a payout, each behind a confirm that says what exactly happens and
 * one `Idempotency-Key` per submission: «Выплачено» (restates amount, card and seller; a banned
 * account or a frozen wallet needs a reason), «Отклонить» (hidden once Skinslink reverted the
 * trade — the API refuses it), «Отменить (откат)» when the sale was reverted, and «Вернуть в
 * очередь» for a decision of the last 10 minutes. The confirm is a bottom sheet on a phone
 * (`ConfirmSheet`); one green button per step; «Отклонить» outlined red on its own row, while
 * «Отменить (откат)» — the request's main action once the trade was reverted — stays in the
 * sticky bar. A confirm closes by itself when a refetch says its action is gone.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PAYOUTS_KEY, payoutKey, saleKey } from "./keys";
import { CARD_BRANDS, last4, payoutErrorText } from "./labels";
import {
  cancelPayout,
  markPaid,
  type PayoutDetail as Detail,
  rejectPayout,
  undoPayout,
} from "./payoutsApi";

import { CONFIRM_BUTTONS, ConfirmSheet, DANGER_OUTLINE } from "@/components/ConfirmSheet";
import { Money } from "@/components/Money";
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

const TITLE: Record<Exclude<Panel, "none">, string> = {
  paid: "Подтвердите выплату",
  reject: "Отклонить заявку",
  cancel: "Отменить заявку (откат)",
  undo: "Вернуть в очередь",
};

/** The one name of closing a reverted sale's request without paying: button, banner, runbook. */
export const CANCEL_LABEL = "Отменить (откат)";

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

/** What is being sent, large: the amount and the card to check against the bank app. */
function PaidSummary({ detail }: { detail: Detail }) {
  const r = detail.request;
  return (
    <div>
      <Money uzs={r.amount_uzs} className="block text-2xl font-bold" />
      <p className="text-lg">
        <span className="font-semibold">{CARD_BRANDS[r.card_type]}</span>{" "}
        <span className="font-mono">•••• {last4(r.card_masked)}</span>
      </p>
    </div>
  );
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
  // Skinslink took the trade back: the API refuses «Отклонить» (it would pay the seller twice).
  const canReject = !(detail.request.flags ?? []).includes("rolled_back");
  const available: Record<Exclude<Panel, "none">, boolean> = {
    paid: detail.can_decide,
    reject: detail.can_decide && canReject,
    cancel: detail.can_cancel === true,
    undo: undoUntil !== null,
  };
  const gone = panel !== "none" && !available[panel];
  // A refetch took the open action away (e.g. `rolled_back` arrived): close its confirm.
  useEffect(() => {
    if (gone) setPanel("none");
  }, [gone]);
  const needsText = panel === "reject" || panel === "cancel" || panel === "undo";
  const needsOverride = panel === "paid" && detail.paid_needs_override === true;
  const blocked =
    act.isPending || (needsText && text.trim() === "") || (needsOverride && override.trim() === "");
  if (!detail.can_decide && undoUntil === null && detail.can_cancel !== true) return null;
  // One green button per step: «Беру в работу» first, then «Выплачено».
  const paidIsNext = by !== null && by.id === meId;
  return (
    <section className="flex flex-col gap-3" aria-label="Решение">
      {/* On a phone the decision stays at the bottom of the screen while the card scrolls. */}
      {detail.can_decide || undoUntil !== null || detail.can_cancel === true ? (
        <div
          data-testid="decision-bar"
          className="bg-bg/95 border-border sticky bottom-0 z-20 -mx-4 flex flex-wrap gap-2 border-t px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none [&>button]:flex-1 sm:[&>button]:flex-none"
        >
          {detail.can_decide ? (
            <Button
              variant={paidIsNext ? "primary" : "secondary"}
              disabled={takenByOther}
              onClick={() => {
                open("paid");
              }}
            >
              Выплачено
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
          {detail.can_cancel === true ? (
            <Button
              variant="secondary"
              className={DANGER_OUTLINE}
              disabled={takenByOther}
              onClick={() => {
                open("cancel");
              }}
            >
              {CANCEL_LABEL}
            </Button>
          ) : null}
        </div>
      ) : null}
      {available.reject ? (
        <div className="flex flex-wrap gap-2 [&>button]:flex-1 sm:[&>button]:flex-none">
          <Button
            variant="secondary"
            className={DANGER_OUTLINE}
            disabled={takenByOther}
            onClick={() => {
              open("reject");
            }}
          >
            Отклонить
          </Button>
        </div>
      ) : null}
      {takenByOther && detail.can_decide ? (
        <p className="text-fg-muted text-sm">Сначала «Забрать себе» — заявку платит другой.</p>
      ) : null}
      {undoUntil !== null && panel === "none" ? (
        <p className="text-fg-muted text-sm">
          Ошиблись? Вернуть можно до {formatDateTime(undoUntil).slice(-5)}.
        </p>
      ) : null}
      {panel !== "none" && !gone ? (
        <ConfirmSheet
          title={TITLE[panel]}
          busy={act.isPending}
          onClose={() => {
            setPanel("none");
          }}
        >
          {panel === "paid" ? <PaidSummary detail={detail} /> : null}
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
                className="border-danger bg-bg text-fg rounded-md border p-2 text-base"
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
              className="border-border bg-bg rounded-md border p-2 text-base"
            />
          </label>
          <div className={CONFIRM_BUTTONS}>
            <Button
              variant="secondary"
              disabled={act.isPending}
              onClick={() => {
                setPanel("none");
              }}
            >
              Отмена
            </Button>
            <Button
              variant={panel === "paid" || panel === "undo" ? "primary" : "danger"}
              size="lg"
              disabled={blocked}
              onClick={() => {
                act.mutate(panel);
              }}
            >
              {CONFIRM[panel]}
            </Button>
          </div>
          {act.isError ? (
            <p role="alert" className="text-danger text-sm">
              {payoutErrorText(act.error)}
            </p>
          ) : null}
        </ConfirmSheet>
      ) : null}
    </section>
  );
}
