/** «Вывел себе…»: the sheet that records money taken out of Skinslink, and what was taken out. */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { addWithdrawal, DESK_KEY, listWithdrawals } from "./api";
import { deskErrorText } from "./labels";
import { TAP } from "./Parts";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { Money } from "@/components/Money";
import { MoneyField } from "@/components/MoneyInput";
import { When } from "@/components/When";

/** An amount in dollars and a note; «Мои деньги на Skinslink» drop by it. */
export function Withdraw({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => addWithdrawal(amount, note.trim() || undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DESK_KEY });
      onClose();
    },
  });
  return (
    <ConfirmSheet title="Вывел себе" busy={save.isPending} onClose={onClose}>
      <MoneyField label="Сколько выведено" unit="$" decimal value={amount} onChange={setAmount} />
      <label className="flex flex-col gap-1 text-sm">
        Куда
        <input
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          placeholder="Например, на карту"
          className="border-border bg-bg h-11 rounded-md border px-3"
        />
      </label>
      {save.isError && (
        <p role="alert" className="text-danger text-sm">
          {deskErrorText(save.error)}
        </p>
      )}
      <div className={CONFIRM_BUTTONS}>
        <Button variant="secondary" className={TAP} disabled={save.isPending} onClick={onClose}>
          Отмена
        </Button>
        <Button
          className={TAP}
          disabled={save.isPending || !(Number(amount) > 0)}
          onClick={() => {
            save.mutate();
          }}
        >
          Записать
        </Button>
      </div>
    </ConfirmSheet>
  );
}

/** What the owner took out, folded: it matters now and then, not on every visit. */
export function Withdrawals() {
  const list = useQuery({ queryKey: [...DESK_KEY, "withdrawals"], queryFn: listWithdrawals });
  const items = list.data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <details className="border-border rounded-lg border">
      <summary className="text-fg-muted hover:text-fg flex min-h-11 cursor-pointer items-center px-3 text-sm">
        Выводы себе ({items.length})
      </summary>
      <ul className="divide-border border-border divide-y border-t" aria-label="Выводы себе">
        {items.map((w) => (
          <li key={w.id} className="flex items-center gap-3 px-3 py-2 text-sm">
            <Money usd={w.amount_usd} />
            <span className="text-fg-muted min-w-0 flex-1 truncate">{w.note}</span>
            <span className="text-fg-dim text-xs">
              <When iso={w.at} />
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}
