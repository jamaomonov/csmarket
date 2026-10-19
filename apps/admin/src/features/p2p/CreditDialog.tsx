/** «Зачислить пользователю»: book an unmatched transfer for a buyer the operator picks. */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { creditIncoming, type Incoming } from "./api";
import { P2P_KEY } from "./keys";
import { wholeSom } from "./labels";

import { Modal } from "@/components/Modal";
import { UserCell } from "@/components/UserCell";
import { listUsers } from "@/features/users/api";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatSum } from "@/lib/format";
import { useDebounced } from "@/lib/useDebounced";

interface CreditDialogProps {
  row: Incoming;
  onClose: () => void;
}

export function CreditDialog({ row, onClose }: CreditDialogProps) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [userId, setUserId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const typed = useDebounced(q.trim(), 250);
  const found = useQuery({
    queryKey: ["admin", "users", "pick", typed],
    queryFn: () => listUsers({ q: typed }),
    enabled: typed.length >= 2,
  });
  const key = useIdempotencyKey("admin-p2p-credit");
  const amount = formatSum(wholeSom(row.amount_uzs));
  const credit = useMutation({
    mutationFn: () => {
      const body = { user_id: userId ?? "", note: note.trim() };
      return creditIncoming(row.id, body, key.keyFor(JSON.stringify({ id: row.id, ...body })));
    },
    onSuccess: () => {
      key.reset();
      void qc.invalidateQueries({ queryKey: P2P_KEY });
      onClose();
    },
  });
  return (
    <Modal
      title={`Зачислить ${amount}`}
      description="Перевод не нашёл заявку. Зачисляйте, только если по чеку ясно, чей он: второе зачисление того же перевода отправит деньги дважды."
      onClose={onClose}
      busy={credit.isPending}
    >
      <label className="flex flex-col gap-1 text-sm">
        Пользователь
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setUserId(null);
          }}
          placeholder="Имя или Steam ID"
          className="border-border bg-bg h-10 rounded-md border px-3"
        />
      </label>
      {typed.length >= 2 && (
        <ul className="divide-border max-h-48 divide-y overflow-y-auto text-sm">
          {(found.data?.items ?? []).map((u) => (
            <li key={u.id}>
              <button
                type="button"
                aria-pressed={u.id === userId}
                onClick={() => {
                  setUserId(u.id);
                }}
                className={`w-full rounded px-2 py-2 text-left ${u.id === userId ? "bg-accent/10" : "hover:bg-surface-hover"}`}
              >
                <UserCell
                  id={u.id}
                  name={u.display_name}
                  avatarUrl={u.avatar_url}
                  sub={u.steam_id}
                />
              </button>
            </li>
          ))}
        </ul>
      )}
      <label className="flex flex-col gap-1 text-sm">
        Основание
        <textarea
          value={note}
          maxLength={300}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          placeholder="Чек от покупателя, время, сумма"
          className="border-border bg-bg rounded-md border p-2"
        />
      </label>
      {credit.isError && (
        <p role="alert" className="text-danger text-sm">
          {errorText(credit.error)}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          variant="danger"
          disabled={userId === null || note.trim().length < 4 || credit.isPending}
          onClick={() => {
            credit.mutate();
          }}
        >
          Зачислить {amount}
        </Button>
        <Button variant="secondary" onClick={onClose}>
          Отмена
        </Button>
      </div>
    </Modal>
  );
}
