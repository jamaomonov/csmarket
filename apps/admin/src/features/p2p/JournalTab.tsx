/** «Журнал»: every HUMO notification, newest first; an unmatched credit can be booked. */
import { Button } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type Incoming, type IncomingResult, listIncoming } from "./api";
import { CreditDialog } from "./CreditDialog";
import { incomingKey } from "./keys";
import { RESULT_LABELS, RESULT_TONES, wholeSom } from "./labels";

import { DataTable } from "@/components/DataTable";
import { SearchBox } from "@/components/Filters";
import { StatusChip } from "@/components/StatusChip";
import { Tabs } from "@/components/Tabs";
import { When } from "@/components/When";
import { formatSum } from "@/lib/format";

const REFRESH_MS = 15_000;
type Filter = "all" | IncomingResult;

export function JournalTab() {
  const [amount, setAmount] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [crediting, setCrediting] = useState<Incoming | null>(null);
  const digits = amount.replace(/\D/g, "");
  const q = useQuery({
    queryKey: incomingKey(digits, filter),
    queryFn: () =>
      listIncoming({
        ...(digits ? { amount: digits } : {}),
        ...(filter === "all" ? {} : { result: filter }),
      }),
    refetchInterval: REFRESH_MS,
  });
  const chip = (r: Incoming) => (
    <StatusChip tone={r.chain_ok === false ? "danger" : RESULT_TONES[r.result]}>
      {RESULT_LABELS[r.result]}
      {r.chain_ok === false ? " · разрыв цепочки" : ""}
    </StatusChip>
  );
  const action = (r: Incoming) =>
    r.can_credit ? (
      <Button
        size="sm"
        variant="secondary"
        onClick={(e) => {
          e.stopPropagation();
          setCrediting(r);
        }}
      >
        Зачислить пользователю
      </Button>
    ) : (
      <span className="text-fg-muted font-mono text-xs">{r.number ?? ""}</span>
    );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox label="Сумма, сум" value={amount} onChange={setAmount} maxLength={12} mono />
        <Tabs<Filter>
          label="Результат"
          variant="segmented"
          value={filter}
          onChange={setFilter}
          items={[
            { key: "all", label: "Все" },
            { key: "unmatched", label: "Не сопоставлены" },
            { key: "matched", label: "Зачислены" },
            { key: "ignored", label: "Не наши" },
          ]}
        />
      </div>
      <DataTable
        label="Входящие уведомления"
        rows={q.data?.items}
        loading={q.isPending}
        rowKey={(r) => r.id}
        empty="Уведомлений пока нет."
        attention={(r) => r.result === "unmatched" && r.kind === "credit"}
        columns={[
          {
            key: "time",
            header: "Время",
            cell: (r) => <When iso={r.bank_time ?? r.received_at} />,
          },
          {
            key: "amount",
            header: "Сумма",
            align: "right",
            cell: (r) =>
              r.amount_uzs === null
                ? "—"
                : `${r.kind === "debit" ? "−" : "+"}${formatSum(wholeSom(r.amount_uzs))}`,
          },
          {
            key: "card",
            header: "Карта",
            cell: (r) => (r.card_last4 ? `•••• ${r.card_last4}` : "—"),
          },
          { key: "source", header: "Откуда", cell: (r) => r.source_text ?? "—" },
          { key: "result", header: "Итог", cell: chip },
          { key: "action", header: "", cell: action },
        ]}
        mobileCard={(r) => (
          <div className="space-y-1.5 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold tabular-nums">
                {r.amount_uzs === null ? "—" : formatSum(wholeSom(r.amount_uzs))}
              </span>
              {chip(r)}
            </div>
            <div className="text-fg-muted flex flex-wrap gap-2 text-xs">
              <When iso={r.bank_time ?? r.received_at} />
              <span>{r.card_last4 ? `•••• ${r.card_last4}` : ""}</span>
            </div>
            {action(r)}
          </div>
        )}
      />
      {crediting !== null && (
        <CreditDialog
          row={crediting}
          onClose={() => {
            setCrediting(null);
          }}
        />
      )}
    </div>
  );
}
