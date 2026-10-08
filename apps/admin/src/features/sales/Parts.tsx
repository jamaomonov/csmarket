/** Pieces shared by the payout and the sale pages. */
import { type ReactNode } from "react";

import { type AdminSaleItem } from "./api";

import { formatSum } from "@/lib/format";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="text-fg-muted w-44 shrink-0">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function ItemList({ items }: { items: AdminSaleItem[] }) {
  return (
    <section>
      <h2 className="mb-2 font-semibold">Предметы</h2>
      <ul className="text-sm">
        {items.map((i) => (
          <li key={i.asset_id} className="border-border flex justify-between border-t py-1.5">
            <span>{i.name}</span>
            <span className="tabular-nums">
              ${i.price_usd} · {formatSum(i.price_uzs)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
