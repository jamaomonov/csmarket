/** The user page's «Продажи»: the latest 20 sales with their skins, and what the user sold. */
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { type AdminUserSale, getUserSales } from "./api";

import { DataTable } from "@/components/DataTable";
import { Money } from "@/components/Money";
import { Section } from "@/components/Section";
import { SkinThumb } from "@/components/SkinThumb";
import { Status } from "@/components/Status";
import { When } from "@/components/When";

/** Skins shown by name in a row; the rest are «+ ещё N». */
const SHOWN = 2;

export function useUserSales(userId: string) {
  return useQuery({
    queryKey: ["admin", "sales", "user", userId],
    queryFn: () => getUserSales(userId),
  });
}

function Skins({ sale }: { sale: AdminUserSale }) {
  const rest = sale.items.length - SHOWN;
  return (
    <div className="min-w-0 space-y-1">
      {sale.items.slice(0, SHOWN).map((i, n) => (
        <div key={`${i.name}-${String(n)}`} className="flex items-center gap-2">
          <SkinThumb url={i.image_url} />
          <span className="truncate">{i.name}</span>
        </div>
      ))}
      {rest > 0 && <div className="text-fg-muted text-xs">+ ещё {rest}</div>}
    </div>
  );
}

export function UserSales({ userId }: { userId: string }) {
  const navigate = useNavigate();
  const sales = useUserSales(userId);
  return (
    <Section title="Продажи">
      <DataTable
        label="Продажи пользователя"
        rows={sales.data?.items}
        loading={sales.isPending}
        error={sales.isError ? "Не удалось загрузить продажи." : undefined}
        rowKey={(s) => s.number}
        empty="Продаж пока не было."
        attention={(s) => s.attention_open}
        onRowClick={(s) => {
          void navigate(`/sales/${s.number}`);
        }}
        columns={[
          {
            key: "number",
            header: "Номер",
            cell: (s) => (
              <Link to={`/sales/${s.number}`} className="font-mono hover:underline">
                {s.number}
              </Link>
            ),
          },
          { key: "skins", header: "Скины", cell: (s) => <Skins sale={s} /> },
          {
            key: "payout",
            header: "Выплата",
            align: "right",
            cell: (s) => <Money uzs={s.payout_uzs} />,
          },
          {
            key: "to",
            header: "Куда",
            cell: (s) => (s.payout_to === "card" ? "карта" : "баланс"),
          },
          { key: "status", header: "Статус", cell: (s) => <Status of="sale" code={s.status} /> },
          {
            key: "created",
            header: "Создана",
            cell: (s) => <When iso={s.created_at} className="text-fg-muted" />,
          },
        ]}
        mobileCard={(s) => (
          <div className="space-y-1.5 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono">{s.number}</span>
              <Money uzs={s.payout_uzs} />
            </div>
            <Skins sale={s} />
            <div className="flex flex-wrap gap-2">
              <Status of="sale" code={s.status} />
              <span className="text-fg-muted">{s.payout_to === "card" ? "карта" : "баланс"}</span>
              <When iso={s.created_at} className="text-fg-dim ml-auto text-xs" />
            </div>
          </div>
        )}
      />
    </Section>
  );
}
