/** «Сменить статус»: the four statuses the owner may set, saved only on «Сохранить». */
import { Button } from "@csmarket/ui";
import { useState } from "react";

import { type DealStatus, type HandStatus } from "./api";
import { DEAL_STATUS } from "./labels";
import { TAP } from "./Parts";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";

const HAND: readonly HandStatus[] = ["agreed", "paid", "received", "cancelled"];

/** `closed` and `reverted` are the system's: no hand change from them or to them. */
export function isHand(s: DealStatus): s is HandStatus {
  return HAND.some((h) => h === s);
}

interface StatusSheetProps {
  current: HandStatus;
  busy: boolean;
  onClose: () => void;
  onSave: (status: HandStatus) => void;
}

export function StatusSheet({ current, busy, onClose, onSave }: StatusSheetProps) {
  const [chosen, setChosen] = useState<HandStatus>(current);
  const dropping = chosen === "cancelled";
  return (
    <ConfirmSheet title="Сменить статус" busy={busy} onClose={onClose}>
      <fieldset className="flex flex-col gap-1">
        <legend className="sr-only">Статус сделки</legend>
        {HAND.map((s) => (
          <label key={s} className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
            <input
              type="radio"
              name="deal-status"
              className="accent-accent size-5"
              checked={chosen === s}
              onChange={() => {
                setChosen(s);
              }}
            />
            {DEAL_STATUS[s].label}
          </label>
        ))}
      </fieldset>
      {dropping && chosen !== current && (
        <p className="text-warning text-sm">
          Отменить можно, пока ничего не отправлено и не продано.
        </p>
      )}
      <div className={CONFIRM_BUTTONS}>
        <Button variant="secondary" className={TAP} disabled={busy} onClick={onClose}>
          Отмена
        </Button>
        <Button
          className={TAP}
          disabled={busy || chosen === current}
          onClick={() => {
            onSave(chosen);
          }}
        >
          Сохранить
        </Button>
      </div>
    </ConfirmSheet>
  );
}
