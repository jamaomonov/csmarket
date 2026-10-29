/** «Сменить статус»: the six statuses as options, saved only on «Сохранить». */
import { Button } from "@csmarket/ui";
import { useState } from "react";

import { type DealStatus } from "./api";
import { DEAL_STATUS } from "./labels";
import { TAP } from "./Parts";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";

interface StatusSheetProps {
  current: DealStatus;
  busy: boolean;
  onClose: () => void;
  onSave: (status: DealStatus) => void;
}

export function StatusSheet({ current, busy, onClose, onSave }: StatusSheetProps) {
  const [chosen, setChosen] = useState<DealStatus>(current);
  const dropping = chosen === "cancelled" || chosen === "reverted";
  return (
    <ConfirmSheet title="Сменить статус" busy={busy} onClose={onClose}>
      <fieldset className="flex flex-col gap-1">
        <legend className="sr-only">Статус сделки</legend>
        {(Object.keys(DEAL_STATUS) as DealStatus[]).map((s) => (
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
          Это только пометка: зачисления и продажи по сделке остаются в прибыли.
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
