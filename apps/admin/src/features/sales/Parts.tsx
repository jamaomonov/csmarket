/** Pieces shared by the payout and the sale pages. */
import { type AdminSaleItem } from "./api";

import { Section } from "@/components/Section";
import { SkinThumb } from "@/components/SkinThumb";
import { formatSum } from "@/lib/format";

export function ItemList({ items }: { items: AdminSaleItem[] }) {
  return (
    <Section title="Предметы">
      <ul className="-my-1.5 text-sm">
        {items.map((i) => (
          <li
            key={i.asset_id}
            className="border-border flex items-center gap-3 border-t py-1.5 first:border-t-0"
          >
            <SkinThumb url={i.image_url} />
            <span className="min-w-0 flex-1 truncate">{i.name}</span>
            <span className="shrink-0 tabular-nums">
              ${i.price_usd} · {formatSum(i.price_uzs)}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
