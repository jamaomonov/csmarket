/** «Склад»: skins the owner took into his own Steam account, with their cost; sold by hand. */
import { Button } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { DESK_KEY, listStock } from "./api";
import { SellForm } from "./SellForm";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { SkinThumb } from "@/components/SkinThumb";
import { When } from "@/components/When";

export function StockPage() {
  const [selling, setSelling] = useState<string | null>(null);
  const stock = useQuery({ queryKey: [...DESK_KEY, "stock"], queryFn: listStock });
  return (
    <section className="space-y-4">
      <PageHeader
        title="Склад"
        back={{ to: "/desk", label: "Мои сделки" }}
        meta={
          stock.data ? (
            <>
              На складе по себестоимости: <Money usd={stock.data.total_cost_usd} />
            </>
          ) : null
        }
      />
      {stock.data?.items.length === 0 && <p className="text-fg-muted">Склад пуст.</p>}
      <ul className="divide-border border-border divide-y rounded-lg border">
        {stock.data?.items.map((i) => (
          <li key={i.id} className="px-3 py-3">
            <div className="flex flex-wrap items-center gap-3">
              <SkinThumb url={i.image_url} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{i.name}</span>
                <span className="text-fg-muted text-xs">
                  <Link to={`/desk/deals/${i.deal_id}`} className="underline">
                    {i.trader}
                  </Link>{" "}
                  · <When iso={i.bought_at} />
                </span>
              </span>
              <span className="text-sm">
                {i.cost_usd ? <Money usd={i.cost_usd} /> : <span className="text-fg-muted">—</span>}
              </span>
              {selling !== i.id && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    setSelling(i.id);
                  }}
                >
                  Продал…
                </Button>
              )}
            </div>
            {selling === i.id && (
              <SellForm
                itemId={i.id}
                onDone={() => {
                  setSelling(null);
                }}
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
