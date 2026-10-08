"use client";

import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";

import { listOrders, ORDERS_KEY, type OrdersPage } from "@/lib/orders";
import { HOLD_SALES_KEY, listSales, SALES_KEY, type SalesPage } from "@/lib/sales";
import { mergeTrades, type MergedTrades } from "@/lib/trades-feed";

export type TradesType = "all" | "purchases" | "sales" | "hold";

export interface TradesFeed {
  status: "pending" | "error" | "success";
  merged: MergedTrades;
  fetchingMore: boolean;
  more: () => void;
  retry: () => void;
}

function useOrdersPages(enabled: boolean) {
  return useInfiniteQuery<
    OrdersPage,
    Error,
    InfiniteData<OrdersPage, string | null>,
    typeof ORDERS_KEY,
    string | null
  >({
    queryKey: ORDERS_KEY,
    queryFn: ({ pageParam }) => listOrders(pageParam ?? undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  });
}

function useSalesPages(enabled: boolean, hold: boolean) {
  return useInfiniteQuery<
    SalesPage,
    Error,
    InfiniteData<SalesPage, string | null>,
    readonly string[],
    string | null
  >({
    queryKey: hold ? HOLD_SALES_KEY : SALES_KEY,
    queryFn: ({ pageParam }) => listSales(pageParam ?? undefined, hold ? "hold" : undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  });
}

/** The purchases and sales a tab shows, as one list newest first. */
export function useTradesFeed(type: TradesType, signedIn: boolean): TradesFeed {
  const wantOrders = type === "all" || type === "purchases";
  const wantSales = type !== "purchases";
  const orders = useOrdersPages(signedIn && wantOrders);
  const sales = useSalesPages(signedIn && wantSales, type === "hold");
  const used = [wantOrders ? orders : null, wantSales ? sales : null].filter((q) => q !== null);
  const merged = mergeTrades(
    {
      items: wantOrders ? (orders.data?.pages.flatMap((p) => p.items) ?? []) : [],
      hasMore: wantOrders && orders.hasNextPage,
    },
    {
      items: wantSales ? (sales.data?.pages.flatMap((p) => p.items) ?? []) : [],
      hasMore: wantSales && sales.hasNextPage,
    },
  );
  return {
    status: used.some((q) => q.isError)
      ? "error"
      : used.some((q) => q.isPending)
        ? "pending"
        : "success",
    merged,
    fetchingMore: used.some((q) => q.isFetchingNextPage),
    more: () => {
      if (merged.next.includes("orders")) void orders.fetchNextPage();
      if (merged.next.includes("sales")) void sales.fetchNextPage();
    },
    retry: () => {
      for (const q of used) if (q.isError) void q.refetch();
    },
  };
}
