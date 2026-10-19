/** Pieces shared by the payout and the sale pages. */
import { steamImageSize } from "@csmarket/utils/skins";
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
          <li key={i.asset_id} className="border-border flex items-center gap-3 border-t py-1.5">
            {i.image_url ? (
              <img
                src={steamImageSize(i.image_url, "128fx96f")}
                alt=""
                width={48}
                height={36}
                loading="lazy"
                className="bg-surface-2 h-9 w-12 shrink-0 rounded object-contain"
              />
            ) : (
              <div className="bg-surface-2 h-9 w-12 shrink-0 rounded" aria-hidden="true" />
            )}
            <span className="min-w-0 flex-1 truncate">{i.name}</span>
            <span className="shrink-0 tabular-nums">
              ${i.price_usd} · {formatSum(i.price_uzs)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
