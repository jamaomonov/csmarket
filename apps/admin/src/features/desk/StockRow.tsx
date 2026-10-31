/** One stock skin: opens its deal; cost, Skinslink's price now and the profit at it; «Продал». */
import { Button } from "@csmarket/ui";
import { Link } from "react-router-dom";

import { type StockItem } from "./api";
import { TAP } from "./Parts";

import { Money } from "@/components/Money";
import { SkinThumb } from "@/components/SkinThumb";
import { When } from "@/components/When";

interface StockRowProps {
  item: StockItem;
  /** Skinslink's price now; `undefined` until asked, or when it does not take the skin. */
  now: string | undefined;
  onSell: () => void;
}

export function StockRow({ item: i, now, onSell }: StockRowProps) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-3">
      <Link
        to={`/desk/deals/${i.deal_id}`}
        className="hover:bg-surface-2 -m-1 flex min-w-0 flex-1 items-center gap-3 rounded p-1"
      >
        <SkinThumb url={i.image_url} />
        <span className="min-w-0 flex-1">
          <span className="block truncate">{i.name}</span>
          <span className="text-fg-muted block truncate text-xs">
            {i.trader} · <When iso={i.bought_at} />
          </span>
        </span>
      </Link>
      <span className="text-right text-sm">
        {i.cost_usd ? <Money usd={i.cost_usd} /> : <span className="text-fg-muted">—</span>}
        {now !== undefined && (
          <span className="text-fg-muted block text-xs">
            Skinslink сейчас <Money usd={now} />
            {i.cost_usd !== null && (
              <>
                {" "}
                · <Money usd={(Number(now) - Number(i.cost_usd)).toFixed(2)} signed />
              </>
            )}
          </span>
        )}
      </span>
      <Button variant="secondary" className={TAP} onClick={onSell}>
        Продал
      </Button>
    </li>
  );
}
