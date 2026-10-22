/** «Заявки»: top-up requests newest first, with the buyer, the card and the time left. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listRequests, type RequestStatus } from "./api";
import { requestsKey } from "./keys";

import { DataTable } from "@/components/DataTable";
import { Status } from "@/components/Status";
import { Tabs } from "@/components/Tabs";
import { UserCell } from "@/components/UserCell";
import { When } from "@/components/When";
import { formatSum } from "@/lib/format";

type Filter = "all" | RequestStatus;

export function RequestsTab() {
  const [filter, setFilter] = useState<Filter>("all");
  const q = useQuery({
    queryKey: requestsKey(filter),
    queryFn: () => listRequests(filter === "all" ? {} : { status: filter }),
    refetchInterval: 15_000,
  });
  return (
    <div className="space-y-3">
      <Tabs<Filter>
        label="Статус"
        variant="segmented"
        value={filter}
        onChange={setFilter}
        items={[
          { key: "all", label: "Все" },
          { key: "pending", label: "Ждут" },
          { key: "paid", label: "Оплачены" },
          { key: "expired", label: "Истекли" },
        ]}
      />
      <DataTable
        label="Заявки P2P"
        rows={q.data?.items}
        loading={q.isPending}
        rowKey={(r) => r.number}
        empty="Заявок пока нет."
        columns={[
          {
            key: "number",
            header: "Номер",
            cell: (r) => <span className="font-mono">{r.number}</span>,
          },
          {
            key: "user",
            header: "Пользователь",
            cell: (r) => (
              <UserCell id={r.user.id} name={r.user.display_name} avatarUrl={r.user.avatar_url} />
            ),
          },
          { key: "amount", header: "Сумма", align: "right", cell: (r) => formatSum(r.amount_uzs) },
          { key: "card", header: "Карта", cell: (r) => r.card_masked },
          {
            key: "status",
            header: "Статус",
            cell: (r) => <Status of="p2pRequest" code={r.status} />,
          },
          {
            key: "created",
            header: "Создана",
            cell: (r) => <When iso={r.created_at} className="text-fg-muted" />,
          },
        ]}
        mobileCard={(r) => (
          <div className="space-y-1.5 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold tabular-nums">{formatSum(r.amount_uzs)}</span>
              <Status of="p2pRequest" code={r.status} />
            </div>
            <UserCell
              id={r.user.id}
              name={r.user.display_name}
              avatarUrl={r.user.avatar_url}
              sub={r.number}
            />
          </div>
        )}
      />
    </div>
  );
}
