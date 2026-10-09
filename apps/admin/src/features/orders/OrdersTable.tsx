/** A short list of orders (the user card, the API key tab): number, skin, price, status. */
import { Link, useNavigate } from "react-router-dom";

import { type AdminOrderRow } from "./api";
import { AttentionBadge, OrderStatusChip } from "./StatusChip";

import { DataTable } from "@/components/DataTable";
import { Money } from "@/components/Money";
import { formatDateTime } from "@/lib/format";

export function OrdersTable({ orders, label }: { orders: AdminOrderRow[]; label: string }) {
  const navigate = useNavigate();
  return (
    <DataTable
      label={label}
      rows={orders}
      rowKey={(o) => o.number}
      empty="Заказов пока не было."
      attention={(o) => o.attention_reason !== null}
      onRowClick={(o) => {
        void navigate(`/orders/${o.number}`);
      }}
      columns={[
        {
          key: "number",
          header: "Номер",
          cell: (o) => (
            <Link to={`/orders/${o.number}`} className="font-mono hover:underline">
              {o.number}
            </Link>
          ),
        },
        { key: "name", header: "Скин", cell: (o) => o.name },
        {
          key: "price",
          header: "Цена",
          align: "right",
          cell: (o) => <Money uzs={o.price_uzs} />,
        },
        {
          key: "status",
          header: "Статус",
          cell: (o) => (
            <div className="flex flex-wrap items-center gap-1">
              <OrderStatusChip status={o.status} protectedUntil={o.protected_until} />
              <AttentionBadge reason={o.attention_reason} />
            </div>
          ),
        },
        {
          key: "created",
          header: "Создан",
          cell: (o) => (
            <span className="text-fg-muted whitespace-nowrap">{formatDateTime(o.created_at)}</span>
          ),
        },
      ]}
      mobileCard={(o) => (
        <div className="space-y-1 text-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono">{o.number}</span>
            <Money uzs={o.price_uzs} />
          </div>
          <div className="truncate">{o.name}</div>
          <div className="flex flex-wrap items-center gap-1">
            <OrderStatusChip status={o.status} protectedUntil={o.protected_until} />
            <AttentionBadge reason={o.attention_reason} />
            <span className="text-fg-dim ml-auto text-xs">{formatDateTime(o.created_at)}</span>
          </div>
        </div>
      )}
    />
  );
}
