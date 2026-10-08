/**
 * «Обмены» shows purchases and sales as one list, newest first, while the API pages each
 * on its own cursor. A merged list may only show what is certainly in order: nothing
 * older than the oldest item loaded from a stream that still has pages.
 */
import type { OrderOut } from "./orders";
import type { SaleOut } from "./sales";

export type TradeEntry =
  | { kind: "order"; at: number; order: OrderOut }
  | { kind: "sale"; at: number; sale: SaleOut };

export interface Stream<T> {
  items: T[];
  hasMore: boolean;
}

export interface MergedTrades {
  entries: TradeEntry[];
  /** The streams to page next for «Показать ещё»; empty when everything is shown. */
  next: ("orders" | "sales")[];
}

/** The two streams as one list, cut where an unloaded page could still fit in. */
export function mergeTrades(orders: Stream<OrderOut>, sales: Stream<SaleOut>): MergedTrades {
  const fromOrders: TradeEntry[] = orders.items.map((order) => ({
    kind: "order",
    at: Date.parse(order.created_at),
    order,
  }));
  const fromSales: TradeEntry[] = sales.items.map((sale) => ({
    kind: "sale",
    at: Date.parse(sale.created_at),
    sale,
  }));
  const oldest = (s: TradeEntry[]) => s.at(-1)?.at ?? Number.POSITIVE_INFINITY;
  const limits = [
    { key: "orders" as const, hasMore: orders.hasMore, at: oldest(fromOrders) },
    { key: "sales" as const, hasMore: sales.hasMore, at: oldest(fromSales) },
  ].filter((s) => s.hasMore);
  const bound = Math.max(Number.NEGATIVE_INFINITY, ...limits.map((s) => s.at));
  const entries = [...fromOrders, ...fromSales]
    .filter((e) => e.at >= bound)
    .sort((a, b) => b.at - a.at);
  return { entries, next: limits.filter((s) => s.at === bound).map((s) => s.key) };
}
