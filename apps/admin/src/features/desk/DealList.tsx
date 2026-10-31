/**
 * The deals list of «Мои сделки»: the status chips' filters, the fetch that merges several
 * statuses (the API takes one), and a row — the dearest skin, the trader, the profit.
 */
import { Link } from "react-router-dom";

import { type DealRow, type DealStatus, listDeals } from "./api";
import { DEAL_STATUS, METHOD } from "./labels";
import { compactUzs } from "./Parts";

import { Money } from "@/components/Money";
import { SkinThumb } from "@/components/SkinThumb";
import { StatusChip } from "@/components/StatusChip";
import { When } from "@/components/When";

export const FILTERS = {
  all: { label: "все", statuses: [] },
  agreed: { label: "ждут оплаты", statuses: ["agreed"] },
  work: { label: "в работе", statuses: ["paid", "received"] },
  closed: { label: "закрыты", statuses: ["closed"] },
  cancelled: { label: "отменены", statuses: ["cancelled"] },
  reverted: { label: "откат", statuses: ["reverted"] },
} as const satisfies Record<string, { label: string; statuses: readonly DealStatus[] }>;
export type Filter = keyof typeof FILTERS;
export const FILTER_KEYS = Object.keys(FILTERS) as Filter[];

/** Where each status stands in the list; a key per status (`all` for no status). */
export type Cursors = Partial<Record<string, string>>;

export interface DealsPage {
  items: DealRow[];
  next: Cursors | null;
}

/** One page of each status asked (the first, or those `cursors` continue), newest first. */
export async function fetchDeals(
  statuses: readonly DealStatus[],
  q: string,
  cursors: Cursors | null,
): Promise<DealsPage> {
  const keys: (DealStatus | null)[] = statuses.length > 0 ? [...statuses] : [null];
  const asked = keys.filter((k) => cursors === null || cursors[k ?? "all"] !== undefined);
  const pages = await Promise.all(
    asked.map(async (k) => {
      const cursor = cursors?.[k ?? "all"];
      const page = await listDeals({
        ...(k !== null && { status: k }),
        ...(q !== "" && { q }),
        ...(cursor !== undefined && { cursor }),
      });
      return { key: k ?? "all", page };
    }),
  );
  const next: Cursors = {};
  for (const { key, page } of pages) {
    if (page.next_cursor !== null) next[key] = page.next_cursor;
  }
  const items = pages
    .flatMap((p) => p.page.items)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  return { items, next: Object.keys(next).length > 0 ? next : null };
}

/** A guarantor deal whose Steam protection is over and the guarantor not yet told. */
export function guarantorDue(d: DealRow, now = new Date()): boolean {
  return (
    d.method === "guarantor" &&
    d.status !== "reverted" &&
    d.protected_until !== null &&
    new Date(d.protected_until) <= now &&
    d.guarantor_released_at === null
  );
}

/**
 * The booked profit and the expected one (booked + Skinslink less the cost of the skins still
 * bound for it): «пока +$A · ≈ +$B» while part of the deal is done. A cancelled deal shows «—».
 */
function RowProfit({ d }: { d: DealRow }) {
  if (d.status === "cancelled") return <span className="text-fg-muted">—</span>;
  const booked = d.resolved || Number(d.profit_usd) !== 0;
  const expected = d.expected_profit_usd;
  if (booked && expected !== null) {
    return (
      <span title="Прибыль пока и ожидаемая по ценам Skinslink">
        пока <Money usd={d.profit_usd} signed /> · ≈ <Money usd={expected} signed />
      </span>
    );
  }
  if (booked) return <Money usd={d.profit_usd} signed />;
  if (expected !== null) {
    return (
      <span title="Ожидаемая прибыль по ценам Skinslink">
        ≈ <Money usd={expected} signed />
      </span>
    );
  }
  return <span className="text-fg-muted">—</span>;
}

function Paid({ d }: { d: DealRow }) {
  if (d.paid_currency === "UZS" && d.paid_amount !== null) {
    return (
      <>
        <span className="whitespace-nowrap">{compactUzs(d.paid_amount)}</span>
        {d.paid_usd !== null && (
          <span className="hidden sm:inline">
            {" "}
            (<Money usd={d.paid_usd} />)
          </span>
        )}
      </>
    );
  }
  if (d.paid_usd !== null) return <Money usd={d.paid_usd} />;
  return <>без цены</>;
}

export function DealRowLink({ d }: { d: DealRow }) {
  const rest = d.items - 1;
  return (
    <Link
      to={`/desk/deals/${d.id}`}
      className="hover:bg-surface-2 flex items-start gap-3 px-3 py-3"
    >
      <SkinThumb url={d.first_item?.image_url} />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1">
          <span className="truncate font-medium">{d.first_item?.name ?? "без скинов"}</span>
          {rest > 0 && <span className="text-fg-muted shrink-0 text-xs">+{rest}</span>}
        </span>
        <span className="text-fg-muted block truncate text-xs">
          {d.trader} · <When iso={d.created_at} /> · {METHOD[d.method]}
        </span>
        {d.note !== null && d.note !== "" && (
          <span className="text-fg-dim block truncate text-xs">{d.note}</span>
        )}
        <span className="mt-1 flex flex-wrap gap-1">
          <StatusChip tone={DEAL_STATUS[d.status].tone}>{DEAL_STATUS[d.status].label}</StatusChip>
          {guarantorDue(d) && <StatusChip tone="success">можно платить гаранту</StatusChip>}
        </span>
      </span>
      <span className="max-w-[45%] shrink-0 text-right">
        <span className="block font-semibold">
          <RowProfit d={d} />
        </span>
        <span className="text-fg-muted block text-xs">
          <Paid d={d} /> → Skinslink{" "}
          {d.skinslink_usd !== null ? <Money usd={d.skinslink_usd} /> : "—"}
        </span>
      </span>
    </Link>
  );
}
